"""
market_radar_data.py
市場雷達資料層 v5
─────────────────────────────────────────────────────────
資料來源策略（全部免費）：
  FinMind（保留）  : TaiwanStockInfo、TaiwanStockInstitutionalInvestorsBuySell
  證交所 openapi   : 個股行情（STOCK_DAY_ALL）、三大法人（T86）、MI_INDEX
  TWSE 即時 API   : 大盤即時指數（mis.twse.com.tw）
  集保官網         : 大戶股權分散表
  公開資訊觀測站   : ETF 成分股
  磁碟快取層       : restart 後不重打任何 API
─────────────────────────────────────────────────────────
v5 修正：
  [核心] get_taiex_index 重寫
    - 移除重複定義（原本 211 行 & 588 行各一份，後者覆蓋前者）
    - MI_INDEX 加入日期驗證：回傳日期不符查詢日期時拒絕採用
      （MI_INDEX 永遠回傳「最近一個盤後結算日」，盤中查今日會拿到昨天的值）
    - 新增 TWSE 即時大盤 API（mis.twse.com.tw），作為盤中主要來源
    - 所有 except 改為記錄錯誤訊息，不再 silent fail
  [修正] Proxy address-already-in-use → app.py 層改用 allow_reuse_address
─────────────────────────────────────────────────────────
"""

from __future__ import annotations
import os
import csv
import io
import json
import time
import requests
import urllib.request
import urllib.parse
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from i18n import t
from pathlib import Path
import uuid
import threading
import ssl
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

load_dotenv()
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
FINMIND_URL   = "https://api.finmindtrade.com/api/v4/data"

# ── 主要 ETF 清單 ─────────────────────────────────────────
MAIN_ETFS = {
    "0050":   "元大台灣50",
    "0056":   "元大高股息",
    "00878":  "國泰永續高股息",
    "00919":  "群益台灣精選高息",
    "00929":  "復華台灣科技優息",
    "006208": "富邦台50",
}

# ── 類股 → 主題類型對照表 ─────────────────────────────────
SECTOR_TYPE_MAP = {
    "半導體":               "半導體",
    "積體電路":             "半導體",
    "IC 設計":              "半導體",
    "晶圓代工":             "半導體",
    "封測":                 "半導體",
    "電腦及週邊設備業":     "AI/伺服器",
    "電腦及周邊":           "AI/伺服器",
    "伺服器":               "AI/伺服器",
    "網路通訊":             "AI/伺服器",
    "通信網路業":           "AI/伺服器",
    "電動車":               "電動車/電池",
    "電池":                 "電動車/電池",
    "汽車零件":             "電動車/電池",
    "車用電子":             "電動車/電池",
    "生技醫療業":           "生技醫療",
    "生技":                 "生技醫療",
    "醫療器材":             "生技醫療",
    "製藥":                 "生技醫療",
    "醫療保健":             "生技醫療",
    "金融保險業":           "金融",
    "金融業":               "金融",
    "銀行業":               "金融",
    "保險業":               "金融",
    "證券業":               "金融",
    "航運業":               "航太/航運",
    "空運":                 "航太/航運",
    "海運":                 "航太/航運",
    "塑膠工業":             "傳產/原物料",
    "鋼鐵工業":             "傳產/原物料",
    "化學工業":             "傳產/原物料",
    "石化":                 "傳產/原物料",
    "水泥工業":             "傳產/原物料",
    "橡膠工業":             "傳產/原物料",
    "光電業":               "光電/面板",
    "光學":                 "光電/面板",
    "面板":                 "光電/面板",
    "電子零組件業":         "其他電子",
    "電子通路業":           "其他電子",
    "電機機械":             "其他電子",
    "電子":                 "其他電子",
}

def _map_sector_to_type(sector: str) -> str:
    if not sector or pd.isna(sector):
        return "其他"
    for key, val in SECTOR_TYPE_MAP.items():
        if key in str(sector):
            return val
    return "其他電子" if "電子" in str(sector) else "其他"


# ══════════════════════════════════════════════════════════
# 磁碟快取層
# ══════════════════════════════════════════════════════════
CACHE_DIR = Path(__file__).parent / "data" / ".cache_radar"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_write_lock = threading.Lock()  # ★ Thread-Safe 寫入鎖

def _cache_key(name: str) -> Path:
    safe = name.replace("/", "_").replace(":", "_").replace(" ", "_")
    return CACHE_DIR / f"{safe}.json"

def _cache_get(key: str, ttl_seconds: int):
    path = _cache_key(key)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        saved_at = cached.get("_saved_at", 0)
        if time.time() - saved_at < ttl_seconds:
            return cached.get("data")
    except Exception:
        pass
    return None

def _is_data_valid(data) -> bool:
    """
    ★ 驗證資料是否有實質內容，避免把空值寫入快取覆蓋有效舊資料。
    - None          → 無效
    - list          → 長度 > 0 且至少有一個非空元素
    - dict          → 至少有一個非 meta (_xxx) 的 key
    - pd.DataFrame  → len > 0
    - 其他           → bool(data) 為 True
    """
    if data is None:
        return False
    if isinstance(data, list):
        return len(data) > 0 and any(data)
    if isinstance(data, dict):
        real_keys = [k for k in data if not k.startswith("_")]
        return len(real_keys) > 0
    if isinstance(data, pd.DataFrame):
        return len(data) > 0
    return bool(data)


def _cache_set(key: str, data, min_rows: int = 1) -> bool:
    """
    ★ 修正版 _cache_set()：資料驗證 + Thread-Safe 原子寫入。

    改動重點：
      1. 寫入前呼叫 _is_data_valid() 驗證資料完整性
      2. list/DataFrame 額外檢查 len >= min_rows
      3. 使用 tmpfile + os.replace 原子操作，防止多執行緒損毀 JSON
      4. 若驗證不通過，靜默 return False，現有快取保持不變

    Returns:
        True  → 寫入成功
        False → 資料無效，拒絕寫入（現有快取不受影響）
    """
    if not _is_data_valid(data):
        return False
    if isinstance(data, (list, pd.DataFrame)) and len(data) < min_rows:
        return False

    path      = _cache_key(key)
    temp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex}")
    try:
        with _write_lock:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"_saved_at": time.time(), "data": data},
                    f,
                    ensure_ascii=False,
                    default=str,
                )
            os.replace(temp_path, path)
        return True
    except Exception as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        print(f"[CACHE] ★ 寫入失敗 key={key}: {exc}")
        return False

def _derive_prefix(key: str) -> str:
    """
    ★ 從快取 key 萃取類型前綴，用於掃描歷史快取。
    例：
      "twse_daily_2026-04-29"  → "twse_daily_"
      "inst_2026-04-28"        → "inst_"
    """
    import re
    m = re.match(r"^(.*?)\d{4}-\d{2}-\d{2}", key)
    if m:
        return m.group(1)
    parts = key.split("_")
    return "_".join(parts[:2]) + "_" if len(parts) >= 2 else key + "_"


def _cache_get_safe(key: str, max_age_days: int = 5) -> tuple:
    """
    ★ 新增：歷史快取備援讀取器。

    當今日 API 回傳空值（_cache_set 拒絕寫入）時，
    呼叫此函式嘗試讀取「最近一次有效的歷史快取」，作為降級顯示使用。

    Args:
        key          : 原始快取 key（如 "twse_daily_2026-04-29"）
        max_age_days : 最多往回掃描幾天（預設 5 個交易日）

    Returns:
        (data, label_str) —— 找到有效歷史快取時
        (None, None)      —— 無任何有效歷史快取

    label_str 範例：「2026-04-28 15:42 的快取」

    使用範例（在 UI 層）：
        df_raw, err = get_twse_daily(date)
        if df_raw.empty:
            hist_data, label = _cache_get_safe(f"twse_daily_{date}")
            if hist_data:
                df_raw = pd.DataFrame(hist_data)
                st.warning(f"⚠️ 今日資料尚未更新，顯示 {label}")
    """
    # 先嘗試讀取 key 本身（不限 TTL，只看內容是否有效）
    path = _cache_key(key)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            data     = cached.get("data")
            saved_at = cached.get("_saved_at", 0)
            if _is_data_valid(data):
                label = datetime.fromtimestamp(saved_at).strftime("%Y-%m-%d %H:%M")
                return data, t("{label} 的快取", label=label)
        except Exception:
            pass

    # 掃描同前綴的歷史快取，取最新的有效一筆
    prefix  = _derive_prefix(key)
    cutoff  = time.time() - max_age_days * 86400
    safe_prefix = prefix.replace("/", "_").replace(":", "_").replace(" ", "_")

    candidates = sorted(
        CACHE_DIR.glob(f"{safe_prefix}*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for candidate in candidates:
        if candidate.stat().st_mtime < cutoff:
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                cached = json.load(f)
            data     = cached.get("data")
            saved_at = cached.get("_saved_at", 0)
            if _is_data_valid(data):
                label = datetime.fromtimestamp(saved_at).strftime("%Y-%m-%d %H:%M")
                return data, t("{label} 的快取（歷史備援）", label=label)
        except Exception:
            continue

    return None, None


def _cache_clear(key: str) -> None:
    path = _cache_key(key)
    if path.exists():
        path.unlink()


# ══════════════════════════════════════════════════════════
# FinMind 通用呼叫
# ══════════════════════════════════════════════════════════
def _call(dataset: str, params: dict,
          ttl: int = 3600) -> tuple[pd.DataFrame, str | None]:
    cache_key = f"finmind_{dataset}_{json.dumps(params, sort_keys=True)}"
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        try:
            return pd.DataFrame(cached), None
        except Exception:
            pass
    try:
        p = {"dataset": dataset, "token": FINMIND_TOKEN}
        p.update(params)
        r = requests.get(FINMIND_URL, params=p, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame(), f"API error {r.status_code}: {r.text[:200]}"
        data = r.json()
        if data.get("msg") != "success":
            return pd.DataFrame(), data.get("msg", t("未知錯誤"))
        rows = data.get("data", [])
        _cache_set(cache_key, rows)
        return pd.DataFrame(rows), None
    except Exception as e:
        return pd.DataFrame(), str(e)


# ══════════════════════════════════════════════════════════
# 日期基準層
# ══════════════════════════════════════════════════════════
def _tw_now() -> datetime:
    """取得台灣當下時間（UTC+8）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)

# ── 台股國定假日（非週六日但市場休市）────────────────────
# 來源：證交所公告，每年更新
_TW_HOLIDAYS: set[str] = {
    # 2025
    "2025-01-01",  # 元旦
    "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-01-31", "2025-02-03",  # 農曆春節
    "2025-02-28",  # 和平紀念日
    "2025-04-03", "2025-04-04",  # 兒童節/清明
    "2025-05-01",  # 勞動節
    "2025-05-30",  # 端午節補假
    "2025-05-31",  # 端午節
    "2025-10-09",  # 重陽節補假
    "2025-10-10",  # 國慶日
    # 2026
    "2026-01-01",  # 元旦
    "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29",
    "2026-01-30",  # 農曆春節
    "2026-02-28",  # 和平紀念日（週六補假）
    "2026-04-03",  # 兒童節
    "2026-04-06",  # 清明補假
    "2026-05-01",  # 勞動節
    "2026-06-19",  # 端午節
    "2026-10-09",  # 重陽節補假
    "2026-10-10",  # 國慶日（週六補假）
}

def _is_holiday(d: datetime) -> bool:
    """判斷是否為台股休市的國定假日（非週六日）。"""
    return d.strftime("%Y-%m-%d") in _TW_HOLIDAYS

def _is_trading_day(d: datetime) -> bool:
    """判斷是否為台股交易日（排除週六日及國定假日）。"""
    return d.weekday() < 5 and not _is_holiday(d)

def _prev_trading_day(d: datetime) -> datetime:
    prev = d - timedelta(days=1)
    while not _is_trading_day(prev):
        prev -= timedelta(days=1)
    return prev

def _price_date() -> str:
    """
    行情日期：用於個股收盤價、漲跌幅（STOCK_DAY_ALL / TPEX mainboard_quotes）。

    時間規則（台灣時間 UTC+8）：
      ┌──────────────────────┬──────────────────────────────────────┐
      │ 時段                  │ 回傳日期                              │
      ├──────────────────────┼──────────────────────────────────────┤
      │ 非交易日               │ 最近一個交易日                        │
      │ 交易日 00:00～08:59   │ 前一交易日                            │
      │ 交易日 09:00～13:29   │ 今日（盤中 TWSE 即時 API 可用）      │
      │ 交易日 13:30～15:29   │ 前一交易日（★ 緩衝期，API 尚未就緒）│
      │ 交易日 15:30 後       │ 今日（STOCK_DAY_ALL 已穩定更新）     │
      └──────────────────────┴──────────────────────────────────────┘
    """
    now = _tw_now()

    if not _is_trading_day(now):
        return _prev_trading_day(now).strftime("%Y-%m-%d")

    h, m = now.hour, now.minute

    if h < 9:
        return _prev_trading_day(now).strftime("%Y-%m-%d")

    if h < 13 or (h == 13 and m < 30):
        # 盤中（09:00～13:29）：今日
        return now.strftime("%Y-%m-%d")

    # ★ 13:30～15:29 緩衝期：收盤後但 STOCK_DAY_ALL 尚未穩定
    if h < 15 or (h == 15 and m < 30):
        return _prev_trading_day(now).strftime("%Y-%m-%d")

    # 15:30 後：盤後資料已就緒
    return now.strftime("%Y-%m-%d")


def _rocslash_to_iso(roc: str) -> str:
    """
    TPEX 民國斜線格式 '115/04/28' → '2026-04-28'。
    """
    parts = str(roc).strip().split("/")
    if len(parts) == 3:
        try:
            return f"{int(parts[0]) + 1911}-{parts[1]}-{parts[2]}"
        except Exception:
            pass
    return ""

def _twse_data_ready() -> bool:
    """
    ★ 修正版：以 15:30 為「資料就緒」時間點，與 _price_date() 保持一致。
    TWSE STOCK_DAY_ALL / TPEX mainboard_quotes 收盤後約 2 小時才穩定更新；
    13:30 收盤 ~ 15:30 前為緩衝期，此區間回傳 False。
    """
    now = _tw_now()
    if not _is_trading_day(now):
        return True
    h, m = now.hour, now.minute
    after_close  = h > 13 or (h == 13 and m >= 30)
    before_ready = h < 15 or (h == 15 and m < 30)   # ★ 15:30 為就緒點
    if after_close and before_ready:
        return False
    return True

def _chip_date() -> str:
    """
    籌碼日期：交易日 16:00 後回傳今日（T86 通常 16:00 後更新），
    否則回傳前一交易日。用於三大法人買賣超。
    """
    now = _tw_now()
    if _is_trading_day(now) and now.hour >= 16:
        return now.strftime("%Y-%m-%d")
    return _prev_trading_day(now).strftime("%Y-%m-%d")

def _latest_trading_date() -> str:
    """相容性保留，等同 _chip_date()。"""
    return _chip_date()

def _rocdate_to_iso(roc: str) -> str:
    """
    把民國日期字串（如 '1150427'）轉為 ISO 格式 '2026-04-27'。
    轉換失敗回傳空字串。
    """
    roc = str(roc).strip()
    if len(roc) == 7:
        try:
            y = int(roc[:3]) + 1911
            m = roc[3:5]
            d = roc[5:7]
            return f"{y}-{m}-{d}"
        except Exception:
            pass
    return ""


# ══════════════════════════════════════════════════════════
# 模組 0：加權指數
# ══════════════════════════════════════════════════════════
def get_taiex_index(date: str = None) -> tuple[float, float, str | None]:
    """
    取得加權指數與漲跌幅%。

    來源優先順序（根據實測結果）：
      1. TWSE 即時大盤 API（mis.twse.com.tw）— 盤中唯一可靠的即時來源
      2. TWSE MI_INDEX openapi — 僅在回傳日期與查詢日期相符時採用
         （MI_INDEX 永遠回傳最近盤後結算日；盤中查今日會拿到昨天的值）
      3. FinMind TaiwanStockPrice — 盤後備援

    所有失敗都會記錄到 errors 清單，最後一併回傳。
    """
    if not date:
        date = _price_date()

    cache_key = f"taiex_index_{date}"
    # TTL 60 秒：盤中需要即時刷新
    cached = _cache_get(cache_key, 60)
    if cached and isinstance(cached, dict) and cached.get("close", 0) > 0:
        return cached["close"], cached["chg_pct"], None

    errors: list[str] = []

    # ── 方法 1：TWSE 即時大盤 API ─────────────────────────
    # mis.twse.com.tw 提供盤中即時大盤指數，不需 token，無日期限制
    # 回傳欄位：z=最新成交, y=昨收, o=開盤, h=最高, l=最低
    try:
        url = (
            "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
            "?ex_ch=tse_t00.tw&json=1&delay=0"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0",
                          "Referer": "https://mis.twse.com.tw/"}
        )
        with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
            raw = json.loads(r.read().decode("utf-8"))

        msg_array = raw.get("msgArray", [])
        if msg_array:
            item  = msg_array[0]
            # ★ 盤後 z 欄位變 "-"，改讀 pz（盤後參考價）再 fallback y
            z_val = item.get("z", "-")
            close = 0.0
            if z_val and z_val != "-":
                try:
                    close = float(z_val)
                except (ValueError, TypeError):
                    pass
            if close == 0.0:
                pz_val = item.get("pz", "-")
                if pz_val and pz_val != "-":
                    try:
                        close = float(pz_val)
                    except (ValueError, TypeError):
                        pass
            prev    = float(item.get("y") or 0)
            chg_pct = round((close - prev) / prev * 100, 2) if prev and close != prev else 0.0
            if close > 0:
                _cache_set(cache_key, {"close": close, "chg_pct": chg_pct})
                return close, chg_pct, None
            else:
                errors.append(t("TWSE即時: z/pz 欄位均為 '-'（盤前/盤後無即時價）"))
        else:
            errors.append(t("TWSE即時: msgArray 為空"))
    except Exception as e:
        errors.append(t("TWSE即時: {e}", e=e))

    # ── 方法 2：TWSE MI_INDEX（加日期驗證）────────────────
    # 關鍵：比對回傳的民國日期與查詢日期，不符就拒絕
    try:
        req = urllib.request.Request(
            "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
            raw = json.loads(r.read().decode("utf-8-sig"))

        if isinstance(raw, list) and raw:
            df_idx = pd.DataFrame(raw)
            mask = df_idx.apply(
                lambda col: col.astype(str).str.contains("加權", na=False)
            ).any(axis=1)
            row = df_idx[mask]

            if not row.empty:
                # ── 日期驗證：民國日期轉 ISO 後比對 ──────
                roc_date = str(row.iloc[0].get("日期", "")).strip()
                iso_date = _rocdate_to_iso(roc_date)
                if iso_date and iso_date != date:
                    errors.append(
                        t("MI_INDEX: 回傳日期 {iso_date} ≠ 查詢日期 {date}，拒絕採用（盤中查今日會拿到昨天的資料）",
                          iso_date=iso_date, date=date)
                    )
                else:
                    def _parse(col):
                        if col and col in row.columns:
                            v = str(row[col].iloc[0]).replace(",", "").replace("+", "").strip()
                            try:    return float(v)
                            except: return 0.0
                        return 0.0

                    close_col  = next((c for c in row.columns if "收盤" in c), None)
                    chg_col    = next((c for c in row.columns if "百分比" in c or "漲跌幅" in c), None)
                    chg_pt_col = next((c for c in row.columns
                                       if "漲跌點" in c or
                                       ("漲跌" in c and "百分" not in c and "幅" not in c)), None)
                    close   = _parse(close_col)
                    chg_pct = _parse(chg_col)
                    if chg_pct == 0.0 and close > 0:
                        chg_pt = _parse(chg_pt_col)
                        if chg_pt:
                            prev = close - chg_pt
                            chg_pct = round(chg_pt / prev * 100, 2) if prev else 0.0
                    if close > 0:
                        _cache_set(cache_key, {"close": close, "chg_pct": chg_pct})
                        return close, chg_pct, None
                    else:
                        errors.append(t("MI_INDEX: 解析到 close=0"))
            else:
                errors.append(t("MI_INDEX: 找不到加權指數列，欄位={cols}", cols=list(df_idx.columns)[:8]))
        else:
            errors.append(t("MI_INDEX: 回傳空（盤後尚未更新或非交易日）"))
    except Exception as e:
        errors.append(f"MI_INDEX: {e}")

    # ── 方法 3：FinMind TaiwanStockPrice（盤後備援）──────
    # FinMind 的個股行情 dataset 不包含大盤指數，
    # 改抓 0050 最新收盤作為大盤代理（僅供盤後 fallback）
    if FINMIND_TOKEN:
        try:
            params = urllib.parse.urlencode({
                "dataset":    "TaiwanStockPrice",
                "data_id":    "0050",
                "start_date": date,
                "end_date":   date,
                "token":      FINMIND_TOKEN,
            })
            req = urllib.request.Request(
                f"{FINMIND_URL}?{params}",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
                raw = json.loads(r.read().decode("utf-8"))
            rows = raw.get("data", [])
            if rows:
                last    = rows[-1]
                close   = float(last.get("close", 0) or 0)
                spread  = float(last.get("spread", 0) or 0)
                prev    = close - spread
                chg_pct = round(spread / prev * 100, 2) if prev else 0.0
                if close > 0:
                    # 這個 close 是 0050 股價，不是大盤指數
                    # 不寫 cache，僅告知失敗讓 UI 顯示 N/A
                    errors.append(
                        t("FinMind: 大盤指數無法從 TaiwanStockPrice 取得（0050={close}，非指數值）", close=close)
                    )
            else:
                errors.append(t("FinMind: date={date} 無資料（status={status}, msg={msg}）",
                                  date=date, status=raw.get('status'), msg=raw.get('msg')))
        except Exception as e:
            errors.append(f"FinMind: {e}")

    return 0.0, 0.0, " | ".join(errors)


# ══════════════════════════════════════════════════════════
# 證交所 / 櫃買 openapi 工具
# ══════════════════════════════════════════════════════════
TWSE_API = "https://openapi.twse.com.tw/v1"
TPEX_API = "https://www.tpex.org.tw/openapi/v1"

def _twse_get(path: str, cache_key: str, ttl: int) -> tuple[pd.DataFrame, str | None]:
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        if not cached:
            _cache_clear(cache_key)
        else:
            return pd.DataFrame(cached), None
    try:
        req = urllib.request.Request(
            f"{TWSE_API}{path}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
            data = json.loads(r.read().decode("utf-8-sig"))
        if not data:
            # ★ 歷史備援：API 空值時回傳最近有效快取
            hist_data, label = _cache_get_safe(cache_key)
            if hist_data:
                return pd.DataFrame(hist_data), t("⚠️ 證交所 API 尚未更新，顯示 {label}", label=label)
            return pd.DataFrame(), t("證交所 API 回傳空資料（盤後尚未更新）")
        _cache_set(cache_key, data)
        return pd.DataFrame(data), None
    except Exception as e:
        return pd.DataFrame(), t("證交所 API 失敗：{e}", e=e)


def _tpex_get(path: str, cache_key: str, ttl: int) -> tuple[pd.DataFrame, str | None]:
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        if not cached:
            _cache_clear(cache_key)
        else:
            return pd.DataFrame(cached), None
    try:
        req = urllib.request.Request(
            f"{TPEX_API}{path}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not data:
            # ★ 歷史備援：API 空值時回傳最近有效快取
            hist_data, label = _cache_get_safe(cache_key)
            if hist_data:
                return pd.DataFrame(hist_data), t("⚠️ 櫃買 API 尚未更新，顯示 {label}", label=label)
            return pd.DataFrame(), t("櫃買 API 回傳空資料（盤後尚未更新）")
        _cache_set(cache_key, data)
        return pd.DataFrame(data), None
    except Exception as e:
        return pd.DataFrame(), t("櫃買 API 失敗：{e}", e=e)

def _twse_rwd_get(date: str, cache_key: str, ttl: int) -> tuple:
    """
    ★ 新增：使用 TWSE rwd afterTrading/STOCK_DAY_ALL（帶日期參數）。

    相比 openapi/STOCK_DAY_ALL（永遠回傳最近盤後結算日），
    此 API 可傳入 date=YYYYMMDD，且回傳 JSON 內含 "date" 欄位供驗證。
    實測：openapi 在下午 6 點仍回傳前日，rwd 版本已正確回傳當日。

    回傳格式與 get_twse_daily() 相容：
      [代號, 名稱, 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌, 成交筆數]
    """
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        if not cached:
            _cache_clear(cache_key)
        else:
            return pd.DataFrame(cached), None

    try:
        yyyymmdd = date.replace("-", "")
        url = (
            f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
            f"?date={yyyymmdd}&response=json"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
            text = r.read().decode("utf-8-sig")

        # ★ TWSE 目前這支 API 即使帶 response=json，實測還是直接回傳 CSV，
        #   不是舊版預期的 {stat, date, fields, data} JSON envelope。
        #   兩種格式都處理，避免之後 TWSE 又切回 JSON 時整個掛掉。
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = None

        if raw is not None:
            stat = raw.get("stat", "")
            if stat != "OK":
                hist_data, label = _cache_get_safe(cache_key)
                if hist_data:
                    return pd.DataFrame(hist_data), t("⚠️ TWSE rwd 尚未更新，顯示 {label}", label=label)
                return pd.DataFrame(), t("TWSE rwd STOCK_DAY_ALL stat={stat}（盤後尚未更新）", stat=stat)

            actual_yyyymmdd = raw.get("date", "")
            if actual_yyyymmdd and actual_yyyymmdd != yyyymmdd:
                hist_data, label = _cache_get_safe(cache_key)
                if hist_data:
                    return pd.DataFrame(hist_data), t("⚠️ TWSE rwd 回傳 {actual}≠{expected}，顯示 {label}", actual=actual_yyyymmdd, expected=yyyymmdd, label=label)
                return pd.DataFrame(), t("TWSE rwd 回傳日期 {actual} ≠ 查詢 {expected}", actual=actual_yyyymmdd, expected=yyyymmdd)

            fields = raw.get("fields", [])
            rows   = raw.get("data", [])
            if not rows:
                hist_data, label = _cache_get_safe(cache_key)
                if hist_data:
                    return pd.DataFrame(hist_data), t("⚠️ TWSE rwd 無資料，顯示 {label}", label=label)
                return pd.DataFrame(), t("TWSE rwd {date} 無資料", date=date)

            df = pd.DataFrame(rows, columns=fields) if fields else pd.DataFrame(rows)

        else:
            csv_rows = list(csv.reader(io.StringIO(text)))
            if len(csv_rows) < 2:
                hist_data, label = _cache_get_safe(cache_key)
                if hist_data:
                    return pd.DataFrame(hist_data), t("⚠️ TWSE rwd 無資料，顯示 {label}", label=label)
                return pd.DataFrame(), t("TWSE rwd {date} 無資料", date=date)

            df = pd.DataFrame(csv_rows[1:], columns=csv_rows[0])

            # ── 日期驗證：用第一筆資料列的「日期」欄位（民國格式）比對 ──
            if "日期" in df.columns and not df.empty:
                actual_iso   = _rocdate_to_iso(str(df.iloc[0]["日期"]).strip())
                expected_iso = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
                if actual_iso and actual_iso != expected_iso:
                    hist_data, label = _cache_get_safe(cache_key)
                    if hist_data:
                        return pd.DataFrame(hist_data), t("⚠️ TWSE rwd 回傳 {actual}≠{expected}，顯示 {label}", actual=actual_iso, expected=expected_iso, label=label)
                    return pd.DataFrame(), t("TWSE rwd 回傳日期 {actual} ≠ 查詢 {expected}", actual=actual_iso, expected=expected_iso)

        records = df.to_dict("records")
        _cache_set(cache_key, records, min_rows=50)
        return df, None

    except Exception as e:
        return pd.DataFrame(), t("TWSE rwd 失敗：{e}", e=e)


def _get_stock_info() -> pd.DataFrame:
    df, _ = _call("TaiwanStockInfo", {}, ttl=86400)
    return df


# ══════════════════════════════════════════════════════════
# 模組 1：類股熱點
# ══════════════════════════════════════════════════════════
def _get_finmind_daily(date: str) -> tuple[pd.DataFrame, str | None]:
    if not FINMIND_TOKEN:
        return pd.DataFrame(), t("未設定 FINMIND_TOKEN")

    cache_key = f"finmind_daily_{date}"
    cached = _cache_get(cache_key, 600)
    if cached is not None and cached:
        return pd.DataFrame(cached), None

    try:
        params = urllib.parse.urlencode({
            "dataset":    "TaiwanStockPrice",
            "start_date": date,
            "end_date":   date,
            "token":      FINMIND_TOKEN,
        })
        req = urllib.request.Request(
            f"{FINMIND_URL}?{params}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as r:
            raw = json.loads(r.read().decode("utf-8"))

        if raw.get("status") != 200 or not raw.get("data"):
            # ★ 歷史備援：嘗試讀取最近一次有效快取
            hist_data, label = _cache_get_safe(cache_key)
            if hist_data:
                return pd.DataFrame(hist_data), t("⚠️ FinMind 尚未更新，顯示 {label}", label=label)
            return pd.DataFrame(), t("FinMind TaiwanStockPrice 無資料（{msg}）", msg=raw.get('msg',''))

        df = pd.DataFrame(raw["data"])
        rename = {
            "stock_id":       "代號",
            "close":          "收盤",
            "spread":         "漲跌",
            "Trading_Volume": "成交量",
            "Trading_money":  "成交金額",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        for col in ["收盤", "漲跌", "成交量", "成交金額"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        if "成交量" in df.columns:
            df["成交量"] = (df["成交量"] / 1000).round(0)

        if "收盤" in df.columns and "漲跌" in df.columns:
            prev = df["收盤"] - df["漲跌"]
            df["漲跌幅%"] = ((df["漲跌"] / prev) * 100).round(2)

        df["日期"] = date
        # ★ min_rows=50：正常交易日上市股票遠超 50 支，否則視為異常空值
        _cache_set(cache_key, df.to_dict("records"), min_rows=50)
        return df, None

    except Exception as e:
        return pd.DataFrame(), t("FinMind daily 失敗：{e}", e=e)


def _merge_sector(df: pd.DataFrame, market_filter: list) -> pd.DataFrame:
    df_info = _get_stock_info()
    if df_info.empty:
        return df
    mc = next((c for c in ["market", "type"] if c in df_info.columns), None)
    if not mc:
        return df
    df_mkt = df_info[df_info[mc].str.lower().isin(market_filter)].copy()
    df_mkt = df_mkt.rename(columns={"stock_id": "代號", "industry_category": "類股"})
    if "代號" in df_mkt.columns and "類股" in df_mkt.columns:
        df = df.merge(df_mkt[["代號", "類股"]], on="代號", how="left")
    return df


def get_twse_daily(date: str = None) -> tuple[pd.DataFrame, str | None]:
    if not date:
        date = (
            _prev_trading_day(_tw_now()).strftime("%Y-%m-%d")
            if not _twse_data_ready()
            else _price_date()
        )

    # ── 假日偵測：非交易日直接用前一交易日 ──────────────────
    try:
        query_dt = datetime.strptime(date, "%Y-%m-%d")
        if not _is_trading_day(query_dt):
            prev_date = _prev_trading_day(query_dt).strftime("%Y-%m-%d")
            df, err = get_twse_daily(prev_date)
            note = t("⚠️ {date} 為休市日，顯示 {prev_date} 資料", date=date, prev_date=prev_date)
            return df, (note if not df.empty else err)
    except Exception:
        pass

    df, err = _get_finmind_daily(date)
    if not df.empty:
        df_info = _get_stock_info()
        if not df_info.empty:
            mc = next((c for c in ["market", "type"] if c in df_info.columns), None)
            if mc:
                twse_codes = set(
                    df_info[df_info[mc].str.lower().isin(["twse", "tse"])]["stock_id"].astype(str)
                )
                df = df[df["代號"].astype(str).isin(twse_codes)].copy()
        df["市場"] = "上市"
        df = _merge_sector(df, ["twse", "tse"])
        if not df.empty:
            return df, None

    # ★ 改用 _twse_rwd_get（帶日期參數，實測回傳當日資料）
    #   取代原本的 openapi/STOCK_DAY_ALL（無日期，盤後更新延遲至隔日）
    cache_key = f"twse_daily_{date}"
    df_price, err = _twse_rwd_get(date, cache_key, ttl=1800)
    if err or df_price.empty:
        return pd.DataFrame(), err or t("{date} 無上市行情資料", date=date)

    # rwd API 欄位為中文：證券代號, 證券名稱, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數
    rename = {
        "證券代號": "代號", "證券名稱": "名稱",
        "收盤價": "收盤", "漲跌價差": "漲跌",
        "成交股數": "成交量", "成交金額": "成交金額",
        # openapi 舊欄位保留相容（萬一 cache 內是舊格式）
        "Code": "代號", "Name": "名稱", "ClosingPrice": "收盤", "Change": "漲跌",
        "TradeVolume": "成交量", "TradeValue": "成交金額",
    }
    df_price = df_price.rename(columns={k: v for k, v in rename.items() if k in df_price.columns})
    for col in ["收盤", "漲跌", "成交量", "成交金額"]:
        if col in df_price.columns:
            df_price[col] = pd.to_numeric(
                df_price[col].astype(str).str.replace(",", "").str.replace("+", ""), errors="coerce")
    if "成交量" in df_price.columns:
        df_price["成交量"] = (df_price["成交量"] / 1000).round(0)
    if "收盤" in df_price.columns and "漲跌" in df_price.columns:
        prev = df_price["收盤"] - df_price["漲跌"]
        df_price["漲跌幅%"] = ((df_price["漲跌"] / prev) * 100).round(2)
    df_price = _merge_sector(df_price, ["twse", "tse"])
    df_price["日期"] = date
    return df_price, None


def get_tpex_daily(date: str = None) -> tuple[pd.DataFrame, str | None]:
    if not date:
        date = (
            _prev_trading_day(_tw_now()).strftime("%Y-%m-%d")
            if not _twse_data_ready()
            else _price_date()
        )

    # ── 假日偵測：非交易日直接用前一交易日 ──────────────────
    try:
        query_dt = datetime.strptime(date, "%Y-%m-%d")
        if not _is_trading_day(query_dt):
            prev_date = _prev_trading_day(query_dt).strftime("%Y-%m-%d")
            df, err = get_tpex_daily(prev_date)
            note = t("⚠️ {date} 為休市日，顯示 {prev_date} 資料", date=date, prev_date=prev_date)
            return df, (note if not df.empty else err)
    except Exception:
        pass

    # ── FinMind 路徑（有日期參數，可信）────────────────────
    df, err = _get_finmind_daily(date)
    if not df.empty:
        df_info = _get_stock_info()
        if not df_info.empty:
            mc = next((c for c in ["market", "type"] if c in df_info.columns), None)
            if mc:
                tpex_codes = set(
                    df_info[df_info[mc].str.lower().isin(["otc", "tpex"])]["stock_id"].astype(str)
                )
                df = df[df["代號"].astype(str).isin(tpex_codes)].copy()
        df["市場"] = "上櫃"
        df = _merge_sector(df, ["otc", "tpex"])
        if not df.empty:
            return df, None

    # ── TPEX openapi 路徑（無日期參數，需驗證回傳日期）────
    cache_key = f"tpex_daily_{date}"
    df_price, err = _tpex_get("/tpex_mainboard_quotes", cache_key, ttl=1800)
    if err or df_price.empty:
        return pd.DataFrame(), err or t("{date} 無上櫃行情資料", date=date)

    # ★ 日期驗證：TPEX 欄位 "日期" 格式為 "115/04/28"
    date_col = next(
        (c for c in df_price.columns if "date" in c.lower() or "日期" in c),
        None
    )
    if date_col and not df_price.empty:
        sample    = str(df_price[date_col].iloc[0]).strip()
        actual_iso = _rocslash_to_iso(sample)
        if actual_iso and actual_iso != date:
            _cache_clear(cache_key)   # 刪掉日期錯誤的 cache
            return pd.DataFrame(), (
                t("TPEX 資料日期 {actual} ≠ 查詢日期 {date}，今日資料尚未更新（通常 15:30 後）",
                  actual=actual_iso, date=date)
            )

    rename = {
        "SecuritiesCompanyCode": "代號", "CompanyName": "名稱",
        "Close": "收盤", "Change": "漲跌",
        "TradingShares": "成交量", "Industry": "類股",
    }
    df_price = df_price.rename(columns={k: v for k, v in rename.items() if k in df_price.columns})
    for col in ["收盤", "漲跌", "成交量"]:
        if col in df_price.columns:
            df_price[col] = pd.to_numeric(
                df_price[col].astype(str).str.replace(",", "").str.replace("+", ""),
                errors="coerce"
            )
    if "成交量" in df_price.columns:
        df_price["成交量"] = (df_price["成交量"] / 1000).round(0)
    if "收盤" in df_price.columns and "漲跌" in df_price.columns:
        prev = df_price["收盤"] - df_price["漲跌"]
        df_price["漲跌幅%"] = ((df_price["漲跌"] / prev) * 100).round(2)
    df_price = _merge_sector(df_price, ["otc", "tpex"])
    df_price["日期"] = date
    return df_price, None

def calc_sector_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "類股" not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=["漲跌幅%", "類股"])
    agg = df.groupby("類股").agg(
        平均漲跌幅=("漲跌幅%", "mean"),
        上漲家數=("漲跌幅%", lambda x: (x > 0).sum()),
        下跌家數=("漲跌幅%", lambda x: (x < 0).sum()),
        持平家數=("漲跌幅%", lambda x: (x == 0).sum()),
        總家數=("漲跌幅%", "count"),
    ).reset_index()
    agg["平均漲跌幅"] = agg["平均漲跌幅"].round(2)
    return agg.sort_values("平均漲跌幅", ascending=False)


# ══════════════════════════════════════════════════════════
# 模組 NEW：漲停板分析
# ══════════════════════════════════════════════════════════
def get_limit_up_stocks(
    date: str = None,
    market: str = "twse",
    threshold_pct: float = 9.5,
) -> tuple[pd.DataFrame, str | None]:
    if not date:
        date = _price_date()          # ← 抓今天

    frames = []
    if market in ("twse", "both"):
        df_tw, err_tw = get_twse_daily(date)
        if not err_tw and not df_tw.empty:
            df_tw["市場"] = "上市"
            frames.append(df_tw)
    if market in ("tpex", "both"):
        df_tp, err_tp = get_tpex_daily(date)
        if not err_tp and not df_tp.empty:
            df_tp["市場"] = "上櫃"
            frames.append(df_tp)

    if not frames:
        return pd.DataFrame(), t("無行情資料，請確認日期是否為交易日")

    df_all = pd.concat(frames, ignore_index=True)
    if "漲跌幅%" not in df_all.columns:
        return pd.DataFrame(), t("行情資料缺少漲跌幅欄位")

    df_lu = df_all[df_all["漲跌幅%"] >= threshold_pct].copy()
    if df_lu.empty:
        return pd.DataFrame(), t("{date} 無漲停個股（門檻 {threshold_pct}%）", date=date, threshold_pct=threshold_pct)

    if all(c in df_lu.columns for c in ["開盤", "最高", "最低"]):
        df_lu["是否一字板"] = (
            (df_lu["開盤"] == df_lu["收盤"]) &
            (df_lu["最高"] == df_lu["收盤"]) &
            (df_lu["最低"] == df_lu["收盤"])
        )
    else:
        vol = pd.to_numeric(df_lu.get("成交量", pd.Series(dtype=float)), errors="coerce").fillna(0)
        df_lu["是否一字板"] = vol < 500

    if "類股" in df_lu.columns:
        df_lu["主題類型"] = df_lu["類股"].apply(_map_sector_to_type)
    else:
        df_lu["主題類型"] = "其他"

    keep = [c for c in [
        "代號", "名稱", "類股", "主題類型", "市場",
        "收盤", "漲跌幅%", "成交量", "是否一字板", "日期",
    ] if c in df_lu.columns]
    return df_lu[keep].sort_values("成交量", ascending=False).reset_index(drop=True), None


def calc_limit_up_summary(df_lu: pd.DataFrame) -> dict:
    if df_lu.empty:
        return {"total": 0, "locked": 0, "consecutive_any": 0,
                "type_counts": {}, "top_type": "—"}
    type_counts = (
        df_lu.groupby("主題類型").size().sort_values(ascending=False).to_dict()
    )
    locked   = int(df_lu["是否一字板"].sum()) if "是否一字板" in df_lu.columns else 0
    top_type = max(type_counts, key=type_counts.get) if type_counts else "—"
    return {
        "total": len(df_lu), "locked": locked, "consecutive_any": 0,
        "type_counts": type_counts, "top_type": top_type,
    }


# ══════════════════════════════════════════════════════════
# 模組 2：三大法人買賣超
# ══════════════════════════════════════════════════════════
def get_institutional_investors(date: str = None) -> tuple[pd.DataFrame, str | None]:
    if not date:
        date = _chip_date()

    # ── 假日偵測：若查詢日為休市日，直接回傳前一交易日資料 ──
    try:
        query_dt = datetime.strptime(date, "%Y-%m-%d")
        if not _is_trading_day(query_dt):
            prev_date = _prev_trading_day(query_dt).strftime("%Y-%m-%d")
            df, err = get_institutional_investors(prev_date)
            if not df.empty:
                return df, t("⚠️ {date} 為休市日，顯示 {prev_date} 資料", date=date, prev_date=prev_date)
    except Exception:
        pass

    date_fmt  = date.replace("-", "")
    cache_key = f"inst_{date}"
    cached    = _cache_get(cache_key, 1800)
    if cached is not None:
        df = pd.DataFrame(cached)
    else:
        try:
            url = (
                f"https://www.twse.com.tw/rwd/zh/fund/T86"
                f"?response=json&date={date_fmt}&selectType=ALL"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as r:
                data = json.loads(r.read().decode("utf-8"))
            stat   = data.get("stat", "")
            rows   = data.get("data", [])
            fields = data.get("fields", [])
            if stat != "OK" or not rows:
                # API 回空（可能是假日或資料未更新）→ 嘗試歷史快取備援
                hist_data, hist_label = _cache_get_safe(cache_key, max_age_days=7)
                if hist_data:
                    return pd.DataFrame(hist_data), t("⚠️ {date} 無資料，顯示{hist_label}", date=date, hist_label=hist_label)
                return pd.DataFrame(), t("三大法人 API stat={stat}，可能非交易日或收盤後才更新", stat=stat)
            df = pd.DataFrame(rows, columns=fields)
            _cache_set(cache_key, df.to_dict("records"))
        except Exception as e:
            # 例外時也嘗試歷史快取備援
            hist_data, hist_label = _cache_get_safe(cache_key, max_age_days=7)
            if hist_data:
                return pd.DataFrame(hist_data), t("⚠️ 連線失敗，顯示{hist_label}", hist_label=hist_label)
            return pd.DataFrame(), t("三大法人抓取失敗：{e}", e=e)

    zh_rename = {
        "證券代號": "代號", "證券名稱": "名稱",
        "外陸資買進股數(不含外資自營商)":   "_外資買",
        "外陸資賣出股數(不含外資自營商)":   "_外資賣",
        "外陸資買賣超股數(不含外資自營商)": "_外資淨",
        "外資自營商買進股數":  "_外資自營買",
        "外資自營商賣出股數":  "_外資自營賣",
        "外資自營商買賣超股數":"_外資自營淨",
        "投信買進股數":   "_投信買",
        "投信賣出股數":   "_投信賣",
        "投信買賣超股數": "_投信淨",
        "自營商買賣超股數": "_自營合計淨",
        "自營商買進股數(自行買賣)":   "_自營買",
        "自營商賣出股數(自行買賣)":   "_自營賣",
        "自營商買賣超股數(自行買賣)": "_自營淨",
        "自營商買進股數(避險)":   "_自營避險買",
        "自營商賣出股數(避險)":   "_自營避險賣",
        "自營商買賣超股數(避險)": "_自營避險淨",
        "三大法人買賣超股數": "_合計淨",
    }
    df = df.rename(columns={k: v for k, v in zh_rename.items() if k in df.columns})

    def _num(col: str) -> pd.Series:
        return (
            pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False).str.strip(),
                errors="coerce",
            ).fillna(0) / 1000
        ).round(0).astype(int)

    if "_外資淨" in df.columns:
        base  = _num("_外資淨")
        addon = _num("_外資自營淨") if "_外資自營淨" in df.columns else 0
        df["外資買賣超(張)"] = base + addon
    elif "_外資買" in df.columns and "_外資賣" in df.columns:
        df["外資買賣超(張)"] = _num("_外資買") - _num("_外資賣")

    if "_投信淨" in df.columns:
        df["投信買賣超(張)"] = _num("_投信淨")
    elif "_投信買" in df.columns and "_投信賣" in df.columns:
        df["投信買賣超(張)"] = _num("_投信買") - _num("_投信賣")

    if "_自營合計淨" in df.columns:
        df["自營商買賣超(張)"] = _num("_自營合計淨")
    elif "_自營淨" in df.columns:
        df["自營商買賣超(張)"] = _num("_自營淨")
    elif "_自營買" in df.columns and "_自營賣" in df.columns:
        df["自營商買賣超(張)"] = _num("_自營買") - _num("_自營賣")

    if "_合計淨" in df.columns:
        df["三大法人合計(張)"] = _num("_合計淨")
    else:
        inst_cols = [c for c in ["外資買賣超(張)", "投信買賣超(張)", "自營商買賣超(張)"] if c in df.columns]
        if inst_cols:
            df["三大法人合計(張)"] = df[inst_cols].sum(axis=1)

    drop_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(columns=drop_cols, errors="ignore")
    df["日期"] = date
    return df, None


def get_inst_history(stock_id: str, days: int = 20) -> list[dict]:
    if not FINMIND_TOKEN:
        return []
    start_date = (datetime.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    cache_key  = f"inst_hist_{stock_id}_{start_date}"
    cached     = _cache_get(cache_key, 1800)
    if cached is not None:
        return cached

    df, err = _call(
        "TaiwanStockInstitutionalInvestorsBuySell",
        {"data_id": stock_id, "start_date": start_date},
        ttl=1800,
    )
    if err or df.empty:
        return []

    result: dict[str, dict] = {}
    for _, row in df.iterrows():
        d   = str(row.get("date", ""))[:10]
        inv = str(row.get("institutional_investors", ""))
        buy = int(float(row.get("buy",  0) or 0))
        sell= int(float(row.get("sell", 0) or 0))
        net = (buy - sell) // 1000
        if d not in result:
            result[d] = {"date": d, "f": 0, "t": 0, "d": 0}
        if "Foreign_Investor" in inv:   result[d]["f"] += net
        elif "Investment_Trust" in inv: result[d]["t"] += net
        elif "Dealer_self" in inv:      result[d]["d"] += net

    history = sorted(result.values(), key=lambda x: x["date"])[-days:]
    _cache_set(cache_key, history)
    return history


def get_investment_trust_consecutive(stock_id: str, days: int = 30) -> int:
    cache_key = f"consecutive_{stock_id}_{days}"
    cached = _cache_get(cache_key, 1800)
    if cached is not None:
        return int(cached)

    nets       = []
    check_date = datetime.today()
    fetched    = 0
    while fetched < days:
        while check_date.weekday() >= 5:
            check_date -= timedelta(days=1)
        date_str = check_date.strftime("%Y-%m-%d")
        df, err  = get_institutional_investors(date_str)
        if not err and not df.empty and "代號" in df.columns:
            row = df[df["代號"] == stock_id]
            if not row.empty and "投信買賣超(張)" in row.columns:
                nets.append(float(row["投信買賣超(張)"].iloc[0]))
        check_date -= timedelta(days=1)
        fetched    += 1

    if not nets:
        return 0

    sign  = 1 if nets[0] > 0 else (-1 if nets[0] < 0 else 0)
    count = 0
    for n in nets:
        cur_sign = 1 if n > 0 else (-1 if n < 0 else 0)
        if cur_sign == sign and sign != 0:
            count += 1
        else:
            break

    result = count * sign
    _cache_set(cache_key, result)
    return result


# ══════════════════════════════════════════════════════════
# 模組 3：集保大戶分析
# ══════════════════════════════════════════════════════════

# ── 歷史累積機制 ──────────────────────────────────────────
# 集保每週僅公布一次最新資料，本機制將每週資料「疊加儲存」
# 讓大戶/散戶折線圖可顯示過去 52 週的完整走勢
# ─────────────────────────────────────────────────────────

TDCC_HISTORY_DIR = CACHE_DIR / "tdcc_history"
TDCC_HISTORY_DIR.mkdir(exist_ok=True)

def _tdcc_history_key(stock_id: str) -> Path:
    """個股歷史累積 JSON 路徑，格式 tdcc_history/<stock_id>.json"""
    sid = str(stock_id).strip().upper()
    return TDCC_HISTORY_DIR / f"{sid}.json"

def _load_tdcc_history(stock_id: str) -> list[dict]:
    """讀取個股歷史集保資料（每筆為一個日期的各級距資料）"""
    path = _tdcc_history_key(stock_id)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_tdcc_history(stock_id: str, records: list[dict]) -> None:
    """
    疊加寫入個股歷史集保資料。
    records 格式：[{"date": "20250101", "level": 12, "people": ..., "unit": ..., "percent": ...}, ...]
    按 date 去重，保留最近 52 週（364 天）
    """
    path = _tdcc_history_key(stock_id)
    existing = _load_tdcc_history(stock_id)

    # 建立以 (date, level) 為 key 的 dict，新資料覆蓋舊資料
    merged: dict[tuple, dict] = {}
    for row in existing:
        key = (str(row.get("date", "")), int(row.get("level", 0)))
        merged[key] = row
    for row in records:
        key = (str(row.get("date", "")), int(row.get("level", 0)))
        merged[key] = row

    # 取 date 欄位最近 364 天
    cutoff_date = (datetime.now() - timedelta(days=364)).strftime("%Y%m%d")
    result = [
        v for v in merged.values()
        if str(v.get("date", "19000101")) >= cutoff_date
    ]
    result.sort(key=lambda x: (str(x.get("date", "")), int(x.get("level", 0))))

    temp = path.with_suffix(f".tmp.{uuid.uuid4().hex}")
    try:
        with _write_lock:
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, default=str)
            os.replace(temp, path)
    except Exception as exc:
        if temp.exists():
            try:
                temp.unlink()
            except Exception:
                pass
        print(f"[TDCC_HIST] 寫入失敗 {stock_id}: {exc}")

def _append_tdcc_full_to_history(df_all: pd.DataFrame) -> None:
    """
    將本次下載的全市場集保資料，依股票代號分批寫入歷史累積檔。
    只處理 unit 欄位尚未÷1000 的原始 df（在 _get_tdcc_full 存 cache 之前呼叫）。
    注意：集保原始 percent 是「占集保全市場庫存比例」，非個股內部比例。
    此處重算為「個股各級距占該股總張數的比例」，才能正確計算大戶/散戶持股%。
    """
    if df_all.empty or "stock_id" not in df_all.columns:
        return

    grouped = df_all.groupby("stock_id", sort=False)
    for sid, grp in grouped:
        sid = str(sid).strip()
        if not sid:
            continue
        records = grp[["date", "level", "people", "unit"]].copy()

        # 重算 percent = 個股各級距張數 / 個股總張數 * 100
        total_unit = pd.to_numeric(records["unit"], errors="coerce").fillna(0).sum()
        if total_unit > 0:
            records["percent"] = (
                pd.to_numeric(records["unit"], errors="coerce").fillna(0) / total_unit * 100
            ).round(4)
        else:
            records["percent"] = 0.0

        # date 欄位統一轉成 YYYYMMDD 字串
        if "date" in records.columns:
            records["date"] = pd.to_datetime(
                records["date"].astype(str), errors="coerce"
            ).dt.strftime("%Y%m%d")
        _save_tdcc_history(sid, records.to_dict("records"))

def get_tdcc_shareholding_with_history(stock_id: str) -> tuple[pd.DataFrame, str | None]:
    """
    取得個股集保資料，優先合併本地歷史累積，提供完整走勢。
    回傳 DataFrame 格式與 get_tdcc_shareholding 相同。
    """
    sid = str(stock_id).strip()

    # 先取得最新集保資料（會觸發歷史寫入）
    df_latest, err = get_tdcc_shareholding(sid)

    # 讀取歷史累積
    hist_records = _load_tdcc_history(sid)

    if not hist_records:
        # 沒有歷史，直接回傳最新
        return df_latest, err

    # 合併：history + latest，以 (date, level) 去重，latest 優先
    df_hist = pd.DataFrame(hist_records)
    if "date" in df_hist.columns:
        # ✅ 統一轉換為 datetime 類型
        df_hist["date"] = pd.to_datetime(
            df_hist["date"].astype(str).str[:8],
            format="%Y%m%d", errors="coerce"
        )
    if "unit" in df_hist.columns:
        df_hist["unit"] = (
            pd.to_numeric(df_hist["unit"], errors="coerce").fillna(0) / 1000
        ).round(0).astype(int)
    df_hist["stock_id"] = sid

    if not df_latest.empty:
        # ✅ 確保 df_latest 的 date 也是 datetime 類型
        if "date" in df_latest.columns:
            df_latest = df_latest.copy()
            df_latest["date"] = pd.to_datetime(df_latest["date"], errors="coerce")
        
        # 合併，最新資料的日期優先
        df_combined = pd.concat([df_hist, df_latest], ignore_index=True)
        
        # ✅ 現在 date 欄位已經是 datetime，可以安全地轉成字串做去重
        df_combined["_date_str"] = pd.to_datetime(
            df_combined["date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        df_combined = df_combined.drop_duplicates(
            subset=["_date_str", "level"], keep="last"
        ).drop(columns=["_date_str"])
    else:
        df_combined = df_hist

    # ✅ 確保排序前 date 是 datetime 類型
    if "date" in df_combined.columns:
        df_combined["date"] = pd.to_datetime(df_combined["date"], errors="coerce")
    
    return df_combined.sort_values(["date", "level"]).reset_index(drop=True), None


def _get_tdcc_full() -> tuple[pd.DataFrame, str | None]:
    """
    下載集保全市場持股分散資料。
    集保 CSV 欄位固定順序（實測確認）：
      序號, 資料日期, 證券代號, 證券名稱, 持股/分級, 人數, 股數, 占集保庫存數比例(%)
    """
    cache_key = "tdcc_full_market"
    cached = _cache_get(cache_key, 86400 * 7)
    if cached is not None:
        df = pd.DataFrame(cached)
        # ✅ 從 cache 讀取後，date 欄位是字串，需要轉回 datetime
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if "unit" in df.columns:
            df["unit"] = (
                pd.to_numeric(df["unit"], errors="coerce").fillna(0) / 1000
            ).round(0).astype(int)
        return df, None

    try:
        import io
        url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5&key=opendata"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as r:
            raw = r.read().decode("utf-8-sig").strip()

        # ── 解析原始資料 ───────────────────────────────────
        if raw.startswith("[") or raw.startswith("{"):
            # JSON 格式
            data   = json.loads(raw)
            df_all = pd.DataFrame(data)
        else:
            # CSV 格式
            df_all = pd.read_csv(io.StringIO(raw), dtype=str, on_bad_lines="skip")

        df_all.columns = [c.strip() for c in df_all.columns]
        orig_cols = list(df_all.columns)

        # ── 欄位映射：精確優先，模糊備援 ─────────────────
        # 集保固定欄位名稱（中文）
        EXACT_MAP = {
            "證券代號":              "stock_id",
            "stock_id":              "stock_id",   # JSON 格式
            "資料日期":              "date",
            "date":                  "date",
            "持股/分級":             "level",
            "持股分級":              "level",
            "level":                 "level",
            "人數":                  "people",
            "people":                "people",
            "股數":                  "unit",
            "unit":                  "unit",
            "占集保庫存數比例(%)":   "percent",
            "占集保庫存數比例":      "percent",
            "percent":               "percent",
        }
        col_map = {}
        mapped  = set()   # 已被 map 的目標欄位名，避免重複 map

        # 第一輪：精確匹配
        for c in orig_cols:
            target = EXACT_MAP.get(c.strip())
            if target and target not in mapped:
                col_map[c] = target
                mapped.add(target)

        # 第二輪：模糊匹配（只補第一輪沒匹配到的）
        for c in orig_cols:
            if c in col_map:        # 已精確 map，跳過
                continue
            cs = c.strip()
            # 「證券代號」的模糊規則：必須同時含「代」和「號」，排除「序號」
            if "stock_id" not in mapped and "代" in cs and "號" in cs and "序" not in cs:
                col_map[c] = "stock_id"; mapped.add("stock_id")
            elif "date" not in mapped and "日期" in cs:
                col_map[c] = "date";     mapped.add("date")
            elif "level" not in mapped and "分級" in cs:
                col_map[c] = "level";    mapped.add("level")
            elif "people" not in mapped and "人數" in cs:
                col_map[c] = "people";   mapped.add("people")
            elif "unit" not in mapped and "股數" in cs:
                col_map[c] = "unit";     mapped.add("unit")
            elif "percent" not in mapped and "比例" in cs:
                col_map[c] = "percent";  mapped.add("percent")

        df_all = df_all.rename(columns=col_map)

        if "stock_id" not in df_all.columns:
            return pd.DataFrame(), (
                t("找不到證券代號欄。原始欄位：{orig_cols}，嘗試 map：{col_map}",
                  orig_cols=orig_cols, col_map=col_map)
            )

        # ── 數值轉換 ───────────────────────────────────────
        df_all["stock_id"] = df_all["stock_id"].astype(str).str.strip()

        # 過濾掉非股票代號列（集保序號是純數字 6 碼以上，股票代號 4-5 碼含可能字母）
        df_all = df_all[df_all["stock_id"].str.match(r"^[0-9A-Z]{4,6}$", na=False)].copy()

        if "date" in df_all.columns:
            df_all["date"] = pd.to_datetime(
                df_all["date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce"
            )

        for col in ["level", "people"]:
            if col in df_all.columns:
                df_all[col] = pd.to_numeric(
                    df_all[col].astype(str).str.replace(",", ""), errors="coerce"
                ).fillna(0).astype(int)

        if "percent" in df_all.columns:
            df_all["percent"] = pd.to_numeric(
                df_all["percent"].astype(str).str.replace(",", ""), errors="coerce"
            ).fillna(0.0)

        if "unit" in df_all.columns:
            df_all["unit"] = pd.to_numeric(
                df_all["unit"].astype(str).str.replace(",", ""), errors="coerce"
            ).fillna(0).astype(int)

        # 移除合計列（level == 17）
        if "level" in df_all.columns:
            df_all = df_all[df_all["level"] != 17]

        # ★ 疊加寫入歷史累積（在 ÷1000 之前，存原始股數）
        try:
            _append_tdcc_full_to_history(df_all.copy())
        except Exception as _e:
            print(f"[TDCC_HIST] append 失敗（不影響主流程）: {_e}")

        # cache 存原始股數，讀回後才 ÷1000
        _cache_set(cache_key, df_all.to_dict("records"))

        if "unit" in df_all.columns:
            df_all["unit"] = (df_all["unit"] / 1000).round(0).astype(int)

        return df_all, None

    except Exception as e:
        return pd.DataFrame(), t("集保下載失敗：{e}", e=e)


def get_tdcc_shareholding(stock_id: str) -> tuple[pd.DataFrame, str | None]:
    sid           = str(stock_id).strip()
    per_stock_key = f"tdcc_{sid}"
    cached        = _cache_get(per_stock_key, 86400 * 7)
    if cached is not None:
        df = pd.DataFrame(cached)
        # ✅ 從 cache 讀取後，date 欄位是字串，需要轉回 datetime
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df, None

    df_all, err = _get_tdcc_full()
    if err:
        return pd.DataFrame(), err
    if df_all.empty:
        return pd.DataFrame(), t("集保全市場資料為空")

    df_all["stock_id"] = df_all["stock_id"].astype(str).str.strip()
    df = df_all[df_all["stock_id"] == sid].copy()
    if df.empty:
        sample = df_all["stock_id"].unique()[:5].tolist()
        return pd.DataFrame(), t("集保無 {sid} 資料（前幾個代號範例：{sample}）", sid=sid, sample=sample)

    _cache_set(per_stock_key, df.to_dict("records"))
    return df, None


def calc_holder_analysis(
    df: pd.DataFrame,
    whale_threshold: int  = 400,
    retail_threshold: int = 10,
) -> dict:
    LEVEL_MIN_LOT = {
        1: 0,  2: 1,  3: 5,  4: 10,  5: 15,  6: 20,
        7: 30, 8: 40, 9: 50, 10: 100, 11: 200,
        12: 400, 13: 600, 14: 800, 15: 1000,
    }

    def whale_levels(threshold):
        return [lv for lv, mn in LEVEL_MIN_LOT.items() if mn >= threshold]
    def retail_levels(threshold):
        return [lv for lv, mn in LEVEL_MIN_LOT.items() if mn <= threshold and lv >= 2]

    level_col = "level" if "level" in df.columns else \
                ("HoldingSharesLevel" if "HoldingSharesLevel" in df.columns else None)

    if df.empty or "date" not in df.columns or level_col is None:
        return {}

    df = df.copy()
    
    # ✅ 關鍵修復：先確保 date 欄位是 datetime 類型
    # 這樣後續所有日期操作都不會有 Timestamp vs str 的問題
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    
    df[level_col]   = pd.to_numeric(df[level_col], errors="coerce").fillna(0).astype(int)
    df["_date_str"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["_date_str"].notna()]

    dates = sorted(df["_date_str"].unique(), reverse=True)
    if not dates:
        return {}

    w_lvls = whale_levels(whale_threshold)
    r_lvls = retail_levels(retail_threshold)

    result: dict = {}
    for i, d in enumerate(dates[:2]):
        tag = "本週" if i == 0 else "上週"
        sub = df[df["_date_str"] == d]
        wh  = sub[sub[level_col].isin(w_lvls)]
        ret = sub[sub[level_col].isin(r_lvls)]
        mid = sub[~sub[level_col].isin(w_lvls + r_lvls + [1])]
        total_unit = sub["unit"].sum()
        # 注意：集保原始 percent 是「占全市場庫存比例」，不能直接加總當大戶持股%
        # 必須用 unit 重算個股內部比例
        def pct(part_df):
            return round(float(part_df["unit"].sum() / total_unit * 100), 2) if total_unit > 0 else 0.0
        result[tag] = {
            "日期":       d,
            "大戶持股%":  pct(wh),
            "散戶持股%":  pct(ret),
            "中戶持股%":  pct(mid),
            "大戶人數":   int(wh["people"].sum()),
            "散戶人數":   int(ret["people"].sum()),
            "中戶人數":   int(mid["people"].sum()),
            "總股東人數": int(sub["people"].sum()),
            "大戶持股張": int(wh["unit"].sum()),
        }

    if "本週" in result and "上週" in result:
        result["大戶持股變化%"]  = round(result["本週"]["大戶持股%"] - result["上週"]["大戶持股%"], 2)
        result["大戶人數變化"]   = result["本週"]["大戶人數"] - result["上週"]["大戶人數"]
        result["總股東人數變化"] = result["本週"]["總股東人數"] - result["上週"]["總股東人數"]
    elif "本週" in result:
        result["大戶持股變化%"]  = 0.0
        result["大戶人數變化"]   = 0
        result["總股東人數變化"] = 0

    history = []
    for d in reversed(dates):
        sub        = df[df["_date_str"] == d]
        total_unit = sub["unit"].sum()
        wh         = sub[sub[level_col].isin(w_lvls)]
        ret        = sub[sub[level_col].isin(r_lvls)]
        if total_unit > 0:
            wh_pct  = round(float(wh["unit"].sum()  / total_unit * 100), 2)
            ret_pct = round(float(ret["unit"].sum() / total_unit * 100), 2)
        else:
            wh_pct  = 0.0
            ret_pct = 0.0
        history.append({"date": d, "whale": wh_pct, "retail": ret_pct})
    result["history"] = history

    latest_date = dates[0] if dates else None
    if latest_date:
        sub0       = df[df["_date_str"] == latest_date]
        total_unit = sub0["unit"].sum()
        result["raw_levels"] = {
            int(row[level_col]): {
                "pct":    round(float(row.get("unit", 0)) / total_unit * 100, 2) if total_unit > 0 else 0.0,
                "people": int(row.get("people", 0)),
                "unit":   int(row.get("unit", 0)),
            }
            for _, row in sub0.iterrows()
            if int(row[level_col]) != 17
        }

    return result

# ══════════════════════════════════════════════════════════
# 快取管理工具
# ══════════════════════════════════════════════════════════
def get_cache_status() -> list[dict]:
    status = []
    for path in sorted(CACHE_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            saved_at = cached.get("_saved_at", 0)
            age_min  = (time.time() - saved_at) / 60
            status.append({
                "快取名稱":      path.stem,
                "更新時間":      datetime.fromtimestamp(saved_at).strftime("%m/%d %H:%M"),
                "已快取(分鐘)":  round(age_min, 1),
            })
        except Exception:
            continue
    return status

def clear_all_cache() -> int:
    count = 0
    for path in CACHE_DIR.glob("*.json"):
        path.unlink()
        count += 1
    return count


# ══════════════════════════════════════════════════════════
# 大盤摘要 & 並行資料建構
# ══════════════════════════════════════════════════════════
def get_market_summary() -> dict:
    price_d = _price_date()
    chip_d  = _chip_date()

    close, chg_pct, err_price = get_taiex_index(price_d)
    df_inst, err_inst          = get_institutional_investors(chip_d)

    foreign_net = trust_net = dealer_net = total_net = None
    if not err_inst and not df_inst.empty:
        def _agg(col):
            if col in df_inst.columns:
                return int(pd.to_numeric(df_inst[col], errors="coerce").fillna(0).sum())
            return None
        foreign_net = _agg("外資買賣超(張)")
        trust_net   = _agg("投信買賣超(張)")
        dealer_net  = _agg("自營商買賣超(張)")
        total_net   = _agg("三大法人合計(張)")

    return {
        "price_date":  price_d,
        "chip_date":   chip_d,
        "price":       close,
        "change_pct":  chg_pct,
        "price_error": err_price,
        "foreign_net": foreign_net,
        "trust_net":   trust_net,
        "dealer_net":  dealer_net,
        "total_net":   total_net,
        "chip_error":  err_inst,
    }


def build_market_data() -> dict:
    price_d = _price_date()
    chip_d  = _chip_date()

    tasks = {
        "taiex": (get_taiex_index,           (price_d,)),
        "twse":  (get_twse_daily,             (price_d,)),
        "tpex":  (get_tpex_daily,             (price_d,)),
        "inst":  (get_institutional_investors, (chip_d,)),
    }

    results: dict = {}
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:
        ctx = None

    def _run(fn, args):
        # 讓 worker thread 也能讀到 st.session_state（t() 需要知道使用者選的語言）
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)
        return fn(*args)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_run, fn, args): name for name, (fn, args) in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                results[name] = (None, str(e))

    return results