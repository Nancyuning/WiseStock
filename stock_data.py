import time
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import urllib.request, json

from strategy import STRATEGY, normalize, first_match

def format_ticker(ticker):
    ticker = ticker.strip().upper()
    if not ticker.endswith(".TW") and not ticker.endswith(".TWO"):
        ticker = ticker + ".TW"
    return ticker


# 上市/上櫃公司「全部清單」快取 — 上市公司清單一天內幾乎不會變，
# 所以整份清單只抓一次，之後每一檔股票的名字查詢都是 dict lookup，
# 不用每一檔各自重打一次 API（原本 18 檔持股要花 ~30 秒就是這樣來的）。
_NAME_MAP_TTL = 86400  # 1 天
_twse_name_cache = {"data": None, "fetched_at": 0}
_tpex_name_cache = {"data": None, "fetched_at": 0}


def _fetch_name_map(cache, url, code_field, name_field):
    now = time.time()
    if cache["data"] is not None and now - cache["fetched_at"] < _NAME_MAP_TTL:
        return cache["data"]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read())
        name_map = {item.get(code_field): item.get(name_field) for item in data if item.get(code_field)}
        cache["data"] = name_map
        cache["fetched_at"] = now
        return name_map
    except Exception:
        return cache["data"] or {}


def _get_twse_name_map():
    return _fetch_name_map(
        _twse_name_cache,
        "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        "Code", "Name",
    )


def _get_tpex_name_map():
    return _fetch_name_map(
        _tpex_name_cache,
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
        "SecuritiesCompanyCode", "CompanyName",
    )


def get_stock_name(ticker):
    """
    取得台股中文名稱
    優先順序：證交所公司列表 API -> 櫃買中心 API -> yfinance -> 代號本身
    """
    ticker_clean = ticker.strip().upper().replace(".TW", "").replace(".TWO", "")

    twse_name = _get_twse_name_map().get(ticker_clean)
    if twse_name:
        return twse_name

    tpex_name = _get_tpex_name_map().get(ticker_clean)
    if tpex_name:
        return tpex_name

    # 3. fallback: yfinance
    try:
        info = yf.Ticker(format_ticker(ticker)).info
        name = info.get("shortName") or info.get("longName") or ticker_clean
        for s in [" Co., Ltd.", " Corporation", " Inc.", " Ltd.", " Co.", " Inc"]:
            name = name.replace(s, "")
        return name.strip()
    except Exception:
        return ticker_clean



# 上市/上櫃「今日收盤價」快取 — TWSE 官方資料，比 yfinance 對台股的更新即時，
# 不會像 yfinance 那樣在收盤後好幾個小時、甚至隔天都還是 NaN（見 get_current_price）。
_PRICE_MAP_TTL = 300  # 5 分鐘
_twse_price_cache = {"data": None, "fetched_at": 0}
_tpex_price_cache = {"data": None, "fetched_at": 0}


def _get_price_map(cache, fetch_fn):
    now = time.time()
    if cache["data"] is not None and now - cache["fetched_at"] < _PRICE_MAP_TTL:
        return cache["data"]
    try:
        df, _err = fetch_fn()
        if df is None or df.empty or "代號" not in df.columns or "收盤" not in df.columns:
            return cache["data"] or {}
        price_map = dict(zip(df["代號"].astype(str), pd.to_numeric(df["收盤"], errors="coerce")))
        cache["data"] = price_map
        cache["fetched_at"] = now
        return price_map
    except Exception:
        return cache["data"] or {}


def _get_official_price(ticker_clean):
    """先查 TWSE（上市），查不到再查 TPEX（上櫃）；兩邊都沒有就回傳 None 交給呼叫端 fallback。"""
    from market_radar_data import get_twse_daily, get_tpex_daily

    for cache, fetch_fn in ((_twse_price_cache, get_twse_daily), (_tpex_price_cache, get_tpex_daily)):
        price = _get_price_map(cache, fetch_fn).get(ticker_clean)
        if price is not None and pd.notna(price):
            return round(float(price), 2)
    return None


def get_current_price(ticker):
    ticker_clean = ticker.strip().upper().replace(".TW", "").replace(".TWO", "")

    official = _get_official_price(ticker_clean)
    if official is not None:
        return official

    # fallback：TWSE/TPEX 查不到（例如興櫃、極冷門標的），退回 yfinance
    try:
        hist = yf.Ticker(format_ticker(ticker)).history(period="5d")
        if hist.empty:
            return None
        return round(hist["Close"].dropna().iloc[-1], 2)
    except Exception:
        return None

def get_price_on_date(ticker, target_date):
    """取得指定日期（或最近交易日）的收盤價"""
    try:
        t = format_ticker(ticker)
        start = pd.to_datetime(target_date) - timedelta(days=7)
        end   = pd.to_datetime(target_date) + timedelta(days=3)
        df = yf.download(t, start=start, end=end, progress=False, auto_adjust=True)
        close = _flatten_close(df)
        if close is None:
            return None
        target = pd.to_datetime(target_date)
        candidates = close.index[close.index <= target]
        if len(candidates) == 0:
            return None
        return round(float(close.loc[candidates[-1]]), 2)
    except Exception:
        return None

def get_price_after_sell(ticker, sell_date, days_after=30):
    """賣出後遺憾追蹤：取得賣出日後第 N 天的收盤價，回傳 (price_30d, price_60d)"""
    p30 = get_price_on_date(ticker, str(pd.to_datetime(sell_date) + timedelta(days=30)))
    p60 = get_price_on_date(ticker, str(pd.to_datetime(sell_date) + timedelta(days=60)))
    return p30, p60

def get_market_level(date_str=None):
    """
    0050 vs 52 週高低，回傳位階標籤。
    深夜或盤前無即時資料時，自動使用最近一個交易日收盤價，不回傳 None。
    """
    try:
        stock = yf.Ticker("0050.TW")
        # 先抓近5日，取最後一筆有效收盤（處理盤前/深夜無資料）
        recent = stock.history(period="5d")
        recent_close = recent["Close"].dropna()
        if recent_close.empty:
            return "無法判斷", None, None
        current_price = round(float(recent_close.iloc[-1]), 2)

        # 52週高點用一年資料計算
        hist = stock.history(period="1y")
        if hist.empty:
            return "無法判斷", current_price, None

        if date_str:
            target = pd.to_datetime(date_str)
            h_filtered = hist[hist.index.date <= target.date()]
            if not h_filtered.empty:
                hist = h_filtered

        high_52w = round(hist["Close"].dropna().max(), 2)
        pct_from_high = (current_price - high_52w) / high_52w * 100

        if pct_from_high >= -5:
            label = "高位（接近52週高點）"
        elif pct_from_high >= -15:
            label = "中位（正常區間）"
        elif pct_from_high >= -25:
            label = "低位（回調整理）"
        else:
            label = "恐慌（大跌中）"
        return label, current_price, round(pct_from_high, 1)
    except Exception:
        return "無法判斷", None, None

def _flatten_close(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
    else:
        close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.squeeze()

def get_relative_strength(ticker, days=60):
    try:
        end   = datetime.today()
        start = end - timedelta(days=days + 10)
        t = format_ticker(ticker)
        s_df = yf.download(t,         start=start, end=end, progress=False, auto_adjust=True)
        b_df = yf.download("0050.TW", start=start, end=end, progress=False, auto_adjust=True)
        sc = _flatten_close(s_df)
        bc = _flatten_close(b_df)
        if sc is None or bc is None:
            return None, None, None
        combined = pd.DataFrame({"s": sc, "b": bc}).dropna()
        if len(combined) < 2:
            return None, None, None
        sr = (combined["s"].iloc[-1] / combined["s"].iloc[0] - 1) * 100
        br = (combined["b"].iloc[-1] / combined["b"].iloc[0] - 1) * 100
        return round(float(sr)-float(br), 2), round(float(sr), 2), round(float(br), 2)
    except Exception:
        return None, None, None

def get_price_history(ticker, days=60):
    try:
        t     = format_ticker(ticker)
        end   = datetime.today()
        start = end - timedelta(days=days + 10)
        df    = yf.download(t, start=start, end=end, progress=False, auto_adjust=True)
        close = _flatten_close(df)
        if close is None or len(close) < 2:
            return None
        close = (close / close.iloc[0]) * 100
        close.index = pd.to_datetime(close.index)
        return close
    except Exception:
        return None

def stress_test(avg_cost, shares, drop_pct=-20):
    cv   = avg_cost * shares
    loss = cv * (drop_pct / 100)
    return {
        "current_value": round(cv, 0),
        "loss":          round(loss, 0),
        "new_value":     round(cv + loss, 0),
        "drop_pct":      drop_pct
    }

def calc_forward_pe(current_price, estimated_eps):
    """根據現價與預估 EPS 計算 Forward P/E"""
    if not estimated_eps or estimated_eps == 0:
        return None
    return round(current_price / estimated_eps, 1)


# ══════════════════════════════════════════════════════════
# 核心診斷函數：check_stock_health
# 新增 RS矩陣、KD、OBV 指標
# ══════════════════════════════════════════════════════════

def _calc_rs(combined_df, days):
    """計算指定天數的 RS，combined_df 需含 s/b 兩欄且已 dropna"""
    if len(combined_df) < days:
        return None
    window = combined_df.iloc[-days:]
    sr = (window["s"].iloc[-1] / window["s"].iloc[0] - 1) * 100
    br = (window["b"].iloc[-1] / window["b"].iloc[0] - 1) * 100
    return round(float(sr) - float(br), 2)

def _calc_kd(high, low, close, n=9, m1=3, m2=3):
    """
    手動計算 KD（隨機指標），不依賴 pandas_ta
    n=9日 RSV，m1/m2=3日平滑
    回傳 (K series, D series)
    """
    low_n  = low.rolling(n).min()
    high_n = high.rolling(n).max()
    denom  = high_n - low_n
    rsv    = ((close - low_n) / denom.replace(0, float("nan"))) * 100

    k = rsv.copy() * float("nan")
    d = rsv.copy() * float("nan")

    # 找第一個有效 RSV 的位置
    first_valid = rsv.first_valid_index()
    if first_valid is None:
        return k, d

    idx_list = rsv.index.tolist()
    start_i  = idx_list.index(first_valid)

    k_val = 50.0
    d_val = 50.0
    for i in range(start_i, len(idx_list)):
        idx = idx_list[i]
        rsv_val = rsv.loc[idx]
        if pd.isna(rsv_val):
            continue
        k_val = (k_val * (m1 - 1) + rsv_val) / m1
        d_val = (d_val * (m2 - 1) + k_val)   / m2
        k.loc[idx] = round(k_val, 2)
        d.loc[idx] = round(d_val, 2)

    return k, d

def _calc_obv(close, volume):
    """計算 OBV（On-Balance Volume）"""
    obv = [0]
    for i in range(1, len(close)):
        if close.iloc[i] > close.iloc[i-1]:
            obv.append(obv[-1] + volume.iloc[i])
        elif close.iloc[i] < close.iloc[i-1]:
            obv.append(obv[-1] - volume.iloc[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=close.index)

def check_stock_health(ticker, avg_cost=None, net_shares=0):
    """
    量價慣性診斷 v2：RS矩陣 + KD + OBV
    回傳健康狀態字典，供計算機頁面使用
    """
    result = {
        # ── 基本 ──────────────────────────────────────────
        "ticker":              ticker,
        "current_price":       None,
        "ma20":                None,
        "ma60":                None,
        "bias_60":             None,
        "bias_20":             None,
        "ma20_slope":          None,
        "ma20_slope_up":       None,   # True=向上彎 False=向下彎
        "pnl_pct":             None,
        # ── 量能 ──────────────────────────────────────────
        "volume_divergence":   False,
        "momentum_exhaustion": False,
        "breakdown_20":        False,
        "breakdown_10":        False,
        "pullback_support":    False,
        # ── RS 矩陣 ───────────────────────────────────────
        "rs_5":                None,   # 5日 RS vs 0050
        "rs_10":               None,   # 10日 RS vs 0050
        "rs_60":               None,   # 60日 RS vs 0050（長期體質）
        "rs_status":           None,   # 🔥 強勢加速 / 趨緩 / 轉弱
        # ── KD 指標 ───────────────────────────────────────
        "k_val":               None,
        "d_val":               None,
        "kd_signal":           None,   # 黃金交叉 / 死亡交叉 / None
        "kd_position":         None,   # 超買區 / 超賣區 / 正常
        # ── OBV 指標 ──────────────────────────────────────
        "obv_slope":           None,   # 近5日 OBV 斜率方向（正/負）
        "obv_warning":         False,  # ⚠️ 量價背離
        # ── 共振訊號 ──────────────────────────────────────
        "dual_golden_cross":   False,  # RS5>0 且 KD黃金交叉
        # ── 錯誤 ──────────────────────────────────────────
        "error":               None,
        # ── ATR（14日平均真實振幅）───────────────────────
        "atr_14":              None,   # 元
        "atr_trail_stop":      None,   # 從最高點回落 N×ATR 的停利參考價
    }

    cfg = STRATEGY["health"]
    try:
        t     = format_ticker(ticker)
        end   = datetime.today()
        # 至少抓 6 個月保證 KD/OBV 資料充足
        start = end - timedelta(days=210)

        df = yf.download(t, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            result["error"] = "無資料"
            return result

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna(subset=["Close"])
        if len(df) < 30:
            result["error"] = "資料不足"
            return result

        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df["Volume"]
        cur    = float(close.iloc[-1])

        # ── 均線 ────────────────────────────────────────
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        cur_ma20 = float(ma20.dropna().iloc[-1])
        cur_ma60 = float(ma60.dropna().iloc[-1])
        cur_ma10 = float(ma10.dropna().iloc[-1])

        result["current_price"] = cur
        result["ma20"]          = round(cur_ma20, 2)
        result["ma60"]          = round(cur_ma60, 2)
        result["bias_60"]       = round((cur / cur_ma60 - 1) * 100, 2)
        result["bias_20"]       = round((cur / cur_ma20 - 1) * 100, 2)

        ma20_vals = ma20.dropna()
        if len(ma20_vals) >= 5:
            slope_val = float(ma20_vals.iloc[-1]) - float(ma20_vals.iloc[-5])
            result["ma20_slope"]          = round(slope_val, 2)
            result["ma20_slope_up"]       = slope_val > 0   # True = EMA20 向上彎

        if avg_cost and avg_cost > 0:
            result["pnl_pct"] = round((cur / avg_cost - 1) * 100, 2)

        # ── 量能指標 ─────────────────────────────────────
        vol_ma20  = float(volume.rolling(20).mean().dropna().iloc[-1])
        last_vol  = float(volume.iloc[-1])

        recent_close = close.iloc[-5:]
        prev_close_5 = close.iloc[-10:-5]
        price_new_high = (len(prev_close_5) > 0 and
                          float(recent_close.max()) >= float(prev_close_5.max()))
        if price_new_high and float(volume.iloc[-5:].mean()) < vol_ma20 * cfg["exhaustion_vol_ratio"]:
            result["momentum_exhaustion"] = True
        result["volume_divergence"] = result["momentum_exhaustion"]

        prev_c   = float(close.iloc[-2]) if len(close) >= 2 else cur
        prev_m20 = float(ma20.dropna().iloc[-2]) if len(ma20.dropna()) >= 2 else cur_ma20
        prev_m10 = float(ma10.dropna().iloc[-2]) if len(ma10.dropna()) >= 2 else cur_ma10

        if prev_c >= prev_m20 and cur < cur_ma20 and last_vol > vol_ma20 * cfg["breakdown_vol_ratio"]:
            result["breakdown_20"] = True
        if prev_c >= prev_m10 and cur < cur_ma10 and last_vol > vol_ma20 * cfg["breakdown_vol_ratio"]:
            result["breakdown_10"] = True

        # ── RS 矩陣（5 / 10 / 60 日）────────────────────
        b_df = yf.download("0050.TW", start=start, end=end, progress=False, auto_adjust=True)
        bc   = _flatten_close(b_df)
        sc   = close.copy()

        if bc is not None:
            combined = pd.DataFrame({"s": sc, "b": bc}).dropna()
            rs5  = _calc_rs(combined, 5)
            rs10 = _calc_rs(combined, 10)
            rs60 = _calc_rs(combined, 60)

            result["rs_5"]  = rs5
            result["rs_10"] = rs10
            result["rs_60"] = rs60

            # RS 狀態判斷
            if rs5 is not None and rs10 is not None and rs60 is not None:
                if rs5 > 0 and rs10 > 0 and rs5 > rs10:
                    result["rs_status"] = "🔥 強勢加速"
                elif rs60 > 0 and rs5 <= 0:
                    result["rs_status"] = "⚠️ 動能趨緩"
                elif rs60 < 0:
                    result["rs_status"] = "🔴 趨勢轉弱"
                else:
                    result["rs_status"] = "🟢 穩定強勢"

        # ── KD 指標（9,3,3）─────────────────────────────
        k_series, d_series = _calc_kd(high, low, close)
        k_valid = k_series.dropna()
        d_valid = d_series.dropna()

        if len(k_valid) >= 2 and len(d_valid) >= 2:
            k_today   = float(k_valid.iloc[-1])
            d_today   = float(d_valid.iloc[-1])
            k_yest    = float(k_valid.iloc[-2])
            d_yest    = float(d_valid.iloc[-2])

            result["k_val"] = round(k_today, 1)
            result["d_val"] = round(d_today, 1)

            # KD 交叉訊號
            if k_today > d_today and k_yest <= d_yest:
                result["kd_signal"] = "黃金交叉"
            elif k_today < d_today and k_yest >= d_yest:
                result["kd_signal"] = "死亡交叉"

            # KD 位置
            if k_today < cfg["kd_oversold"]:
                result["kd_position"] = "超賣區"
            elif k_today > cfg["kd_overbought"]:
                result["kd_position"] = "超買區"
            else:
                result["kd_position"] = "正常"

        # ── ATR（14日）────────────────────────────────────
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr_14 = float(tr.rolling(14).mean().dropna().iloc[-1])
        result["atr_14"] = round(atr_14, 2)
        high_60 = float(close.iloc[-60:].max()) if len(close) >= 60 else float(close.max())
        result["atr_trail_stop"] = round(high_60 - cfg["atr_multiplier"] * atr_14, 2)

        # ── OBV 指標 ─────────────────────────────────────
        obv_series = _calc_obv(close, volume)

        if len(obv_series) >= 5:
            obv_5 = obv_series.iloc[-5:]
            # 斜率：用首尾差
            obv_slope = float(obv_5.iloc[-1]) - float(obv_5.iloc[0])
            result["obv_slope"] = round(obv_slope, 0)

            # OBV 警告：近3日價格創新高但 OBV 下降
            if len(close) >= 3 and len(obv_series) >= 3:
                price_3d_high = float(close.iloc[-1]) >= float(close.iloc[-3:].max())
                obv_3d_down   = float(obv_series.iloc[-1]) < float(obv_series.iloc[-3])
                if price_3d_high and obv_3d_down:
                    result["obv_warning"] = True

        # ── 逢低回測支撐（加碼點）────────────────────────
        is_uptrend   = (result["ma20_slope"] and result["ma20_slope"] > 0) and (result["rs_60"] and result["rs_60"] > 0)
        is_near_supp = (result["bias_20"] is not None and 0 <= result["bias_20"] <= cfg["pullback_bias_max"]
                        and not result["breakdown_20"])
        if is_uptrend and is_near_supp:
            result["pullback_support"] = True

        # ── 雙黃金共振 ────────────────────────────────────
        if result["rs_5"] is not None and result["rs_5"] > 0 and result["kd_signal"] == "黃金交叉":
            result["dual_golden_cross"] = True

    except Exception as e:
        result["error"] = str(e)

    return result


# ══════════════════════════════════════════════════════════
# 市場震盪機率引擎
# ══════════════════════════════════════════════════════════

def get_market_risk_score():
    """
    震盪機率引擎：綜合 4 個指標計算當前市場風險分數
    使用季線乖離率取代 52週高點，允許順勢行情
    """
    breakdown = {
        "rsi_score": None, "bias_score": None,
        "vol_score": None, "vix_score":  None,
        "rsi_val":   None, "bias_val":   None,
        "vol_val":   None, "vix_val":    None,
        "market_label": None,
    }
    try:
        end   = datetime.today()
        start = end - timedelta(days=400)

        df0 = yf.download("0050.TW", start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(df0.columns, pd.MultiIndex):
            df0.columns = df0.columns.get_level_values(0)
        df0    = df0.dropna(subset=["Close"])
        close0 = df0["Close"]
        cur0   = float(close0.iloc[-1])

        # RSI(14)
        delta   = close0.diff()
        gain    = delta.where(delta > 0, 0).rolling(14).mean()
        loss    = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_val = float(100 - (100 / (1 + gain / loss)).iloc[-1])

        # 季線乖離率
        ma60_0     = close0.rolling(60).mean()
        cur_ma60_0 = float(ma60_0.dropna().iloc[-1])
        bias_val   = (cur0 / cur_ma60_0 - 1) * 100

        # 20日年化波動率
        returns = close0.pct_change().dropna()
        vol_20  = float(returns.iloc[-20:].std() * (252 ** 0.5) * 100) if len(returns) >= 20 else 15.0

        # VIX
        vix_val = 18.0
        try:
            dfv = yf.download("^VIX", start=end - timedelta(days=10),
                              end=end, progress=False, auto_adjust=True)
            if not dfv.empty:
                if isinstance(dfv.columns, pd.MultiIndex):
                    dfv.columns = dfv.columns.get_level_values(0)
                vix_val = float(dfv["Close"].dropna().iloc[-1])
        except Exception:
            pass

        # 正規化 0~100，再依權重加總
        cfg   = STRATEGY["market_risk"]
        norm  = cfg["normalize"]
        w     = cfg["weights"]
        rsi_score  = normalize(rsi_val,  norm["rsi"])
        bias_score = normalize(bias_val, norm["bias"])
        vol_score  = normalize(vol_20,   norm["vol"])
        vix_score  = normalize(vix_val,  norm["vix"])

        osc_prob = round(
            rsi_score * w["rsi"] + bias_score * w["bias"] +
            vol_score * w["vol"] + vix_score  * w["vix"], 1
        )

        osc_days = first_match(osc_prob, cfg["osc_days"], cfg["osc_days_default"])

        r = cfg["ratio"]
        suggested_ratio = max(r["min"], min(r["max"], round(r["base"] - osc_prob * r["slope"], 1)))

        market_label = first_match(bias_val, cfg["market_label"], cfg["market_label_default"])

        breakdown.update({
            "rsi_score":    round(rsi_score,  1),
            "bias_score":   round(bias_score, 1),
            "vol_score":    round(vol_score,  1),
            "vix_score":    round(vix_score,  1),
            "rsi_val":      round(rsi_val,    1),
            "bias_val":     round(bias_val,   1),
            "vol_val":      round(vol_20,     1),
            "vix_val":      round(vix_val,    1),
            "market_label": market_label,
        })

        return {
            "oscillation_prob": osc_prob,
            "oscillation_days": osc_days,
            "suggested_ratio":  suggested_ratio,
            "breakdown":        breakdown,
            "error":            None,
        }

    except Exception as e:
        return {
            "oscillation_prob": 30.0,
            "oscillation_days": 60,
            "suggested_ratio":  70.0,
            "breakdown":        breakdown,
            "error":            str(e),
        }

# ══════════════════════════════════════════════════════════
# 儀表板三燈號訊號函數
# ══════════════════════════════════════════════════════════

def check_stock_signals(ticker, avg_cost=None):
    """
    計算三個儀表板燈號：動能狀態、進場時機、量價配合
    直接呼叫 check_stock_health 後轉換成燈號結論
    回傳 dict：
      momentum_label  : str  動能狀態文字
      momentum_emoji  : str  emoji
      timing_label    : str  進場時機文字
      timing_emoji    : str
      volume_label    : str  量價配合文字
      volume_emoji    : str
      rsi_val         : float
      k_val / d_val   : float
      obv_slope       : float
      rs_5/rs_30/rs_60: float  (rs_30 用 rs_10 代理)
    """
    h = check_stock_health(ticker, avg_cost=avg_cost)

    rs5  = h.get("rs_5")
    rs10 = h.get("rs_10")   # 用作 rs_30 代理
    rs60 = h.get("rs_60")

    # ── A. 動能狀態 (RS 矩陣結論) ─────────────────────────
    # 只要 rs60 有值就能判斷，rs5/rs10 缺了降級處理
    if rs60 is not None:
        if rs5 is not None and rs10 is not None and rs5 > 0 and rs10 > 0 and rs60 > 0 and rs5 > rs10:
            momentum_label = "強力噴發"
            momentum_emoji = "🚀"
        elif (rs10 is not None and rs10 > 0) or (rs10 is None and rs60 > 0):
            momentum_label = "趨勢偏多"
            momentum_emoji = "📈"
        elif (rs10 is not None and rs10 < 0) or (rs10 is None and rs60 < 0):
            momentum_label = "盤整/弱勢"
            momentum_emoji = "💤"
        else:
            momentum_label = "中性觀察"
            momentum_emoji = "➡️"
    elif rs10 is not None:
        # rs60 抓不到但 rs10 有，降級判斷
        momentum_label = "趨勢偏多" if rs10 > 0 else "盤整/弱勢"
        momentum_emoji = "📈" if rs10 > 0 else "💤"
    else:
        momentum_label = "資料不足"
        momentum_emoji = "❓"

    # ── B. 進場時機 (KD + RSI) ─────────────────────────────
    kd_sig = h.get("kd_signal")
    kd_pos = h.get("kd_position")
    k_val  = h.get("k_val")
    d_val  = h.get("d_val")

    # 需要 RSI 數值，從 check_stock_health 沒有直接回傳，用 stock_health 重新算
    rsi_val = None
    try:
        t   = format_ticker(ticker)
        end = datetime.today()
        df_rsi = yf.download(t, start=end - timedelta(days=60),
                             end=end, progress=False, auto_adjust=True)
        if not df_rsi.empty:
            if isinstance(df_rsi.columns, pd.MultiIndex):
                df_rsi.columns = df_rsi.columns.get_level_values(0)
            c = df_rsi["Close"].dropna()
            delta = c.diff()
            gain  = delta.where(delta > 0, 0).rolling(14).mean()
            loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi_s = 100 - (100 / (1 + gain / loss))
            rsi_val = round(float(rsi_s.dropna().iloc[-1]), 1)
    except Exception:
        pass

    sig_cfg = STRATEGY["signals"]
    if rsi_val is not None and rsi_val > sig_cfg["rsi_overheat"]:
        timing_label = "過熱不追"
        timing_emoji = "🔥"
    elif kd_sig == "死亡交叉":
        timing_label = "KD死叉出場"
        timing_emoji = "⚠️"
    elif kd_sig == "黃金交叉" and (rsi_val is None or rsi_val < sig_cfg["golden_cross_rsi_max"]):
        timing_label = "建議加碼"
        timing_emoji = "✅"
    elif kd_pos == "超賣區":
        timing_label = "超賣留意"
        timing_emoji = "🟢"
    elif kd_pos == "超買區":
        timing_label = "超買謹慎"
        timing_emoji = "🟡"
    else:
        timing_label = "觀察等待"
        timing_emoji = "⏳"

    # ── C. 量價配合 (OBV) ────────────────────────────────
    obv_slope   = h.get("obv_slope")
    obv_warning = h.get("obv_warning", False)

    if obv_warning:
        volume_label = "誘多背離"
        volume_emoji = "⚠️"
    elif obv_slope is not None and obv_slope > 0:
        volume_label = "價量齊揚"
        volume_emoji = "✅"
    elif obv_slope is not None and obv_slope < 0:
        volume_label = "量縮留意"
        volume_emoji = "🔻"
    else:
        volume_label = "量能持平"
        volume_emoji = "➡️"

    return {
        "momentum_label": momentum_label,
        "momentum_emoji": momentum_emoji,
        "timing_label":   timing_label,
        "timing_emoji":   timing_emoji,
        "volume_label":   volume_label,
        "volume_emoji":   volume_emoji,
        "rsi_val":        rsi_val,
        "k_val":          k_val,
        "d_val":          d_val,
        "obv_slope":      obv_slope,
        "rs_5":           rs5,
        "rs_30":          rs10,
        "rs_60":          rs60,
        "raw":            h,   # 保留原始 health dict 供計算機使用
    }