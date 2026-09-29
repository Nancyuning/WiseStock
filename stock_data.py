import time
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import urllib.request, json


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
# 技術指標：RS、KD、OBV
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
