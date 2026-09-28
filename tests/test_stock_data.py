"""
stock_data.py 裡不打網路、純計算的技術指標函式測試。
"""
import json
from unittest.mock import patch, MagicMock

import pandas as pd

import stock_data
import stock_chart_widget
from stock_data import stress_test, calc_forward_pe, _calc_rs, _calc_kd, _calc_obv


def test_stress_test_basic():
    result = stress_test(avg_cost=100, shares=10, drop_pct=-20)
    assert result["current_value"] == 1000
    assert result["loss"] == -200
    assert result["new_value"] == 800
    assert result["drop_pct"] == -20


def test_calc_forward_pe_normal():
    assert calc_forward_pe(current_price=100, estimated_eps=10) == 10.0


def test_calc_forward_pe_zero_eps_returns_none():
    assert calc_forward_pe(current_price=100, estimated_eps=0) is None
    assert calc_forward_pe(current_price=100, estimated_eps=None) is None


def test_calc_rs_returns_none_when_not_enough_rows():
    df = pd.DataFrame({"s": [1, 2], "b": [1, 2]})
    assert _calc_rs(df, days=3) is None


def test_calc_rs_outperformance():
    # 個股最後3天 30->50（+66.67%），大盤最後3天 30->34（+13.33%）
    df = pd.DataFrame({
        "s": [10, 20, 30, 40, 50],
        "b": [10, 20, 30, 32, 34],
    })
    assert _calc_rs(df, days=3) == 53.33


def test_calc_kd_stays_within_bounds():
    close = pd.Series([10, 11, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13, 14, 13, 12])
    high  = close + 0.5
    low   = close - 0.5

    k, d = _calc_kd(high, low, close, n=9)

    valid_k = k.dropna()
    valid_d = d.dropna()
    assert len(valid_k) > 0
    assert (valid_k.between(0, 100)).all()
    assert (valid_d.between(0, 100)).all()


def test_calc_obv_matches_manual_calc():
    close  = pd.Series([10, 11, 10, 10, 12])
    volume = pd.Series([100, 200, 150, 80, 300])

    obv = _calc_obv(close, volume)

    assert list(obv) == [0, 200, 50, 50, 350]


def test_stock_chart_widget_reuses_the_same_kd_and_obv():
    """個股分析頁跟技術圖表頁以前各自實作了一份 KD（公式不同，算出來的數字會兜不起來）。
    這裡鎖定兩邊現在是同一份函式，不要再各自維護一份。"""
    assert stock_chart_widget._calc_kd is stock_data._calc_kd
    assert stock_chart_widget._calc_obv is stock_data._calc_obv


def _fake_json_response(payload):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return cm


def test_get_stock_name_fetches_full_list_once_for_multiple_tickers():
    """不同股票各自查名字，不該每一檔都重新打一次 API — 這是造成監控中心
    載入 18 檔持股要 ~30 秒的效能問題，get_stock_name 應該只抓一次全部清單。"""
    stock_data._twse_name_cache["data"] = None
    stock_data._twse_name_cache["fetched_at"] = 0

    payload = [
        {"Code": "2330", "Name": "台積電"},
        {"Code": "0050", "Name": "元大台灣50"},
    ]
    with patch("stock_data.urllib.request.urlopen",
               return_value=_fake_json_response(payload)) as mock_urlopen:
        name1 = stock_data.get_stock_name("2330")
        name2 = stock_data.get_stock_name("0050")

    assert name1 == "台積電"
    assert name2 == "元大台灣50"
    assert mock_urlopen.call_count == 1


def test_get_stock_name_falls_back_to_stale_cache_on_fetch_error():
    stock_data._twse_name_cache["data"] = {"2330": "台積電"}
    stock_data._twse_name_cache["fetched_at"] = 0  # 視為已過期

    with patch("stock_data.urllib.request.urlopen", side_effect=OSError("network down")):
        name = stock_data.get_stock_name("2330")

    assert name == "台積電"


def test_get_current_price_prefers_official_twse_data(monkeypatch):
    """監控中心之前會卡在 yfinance 的落後資料（見 get_current_price fallback），
    官方 TWSE/TPEX 資料查得到時應該優先採用，不要碰 yfinance。"""
    stock_data._twse_price_cache["data"] = None
    stock_data._twse_price_cache["fetched_at"] = 0

    def fake_get_twse_daily(date=None):
        return pd.DataFrame({"代號": ["2330"], "收盤": [2480.0]}), None

    monkeypatch.setattr("market_radar_data.get_twse_daily", fake_get_twse_daily)

    def _boom(*a, **kw):
        raise AssertionError("不該呼叫 yfinance —— 官方資料已經查得到")

    monkeypatch.setattr(stock_data.yf, "Ticker", _boom)

    assert stock_data.get_current_price("2330") == 2480.0


def test_get_current_price_falls_back_to_yfinance_when_official_missing(monkeypatch):
    stock_data._twse_price_cache["data"] = None
    stock_data._twse_price_cache["fetched_at"] = 0
    stock_data._tpex_price_cache["data"] = None
    stock_data._tpex_price_cache["fetched_at"] = 0

    def empty_daily(date=None):
        return pd.DataFrame(), "查無資料"

    monkeypatch.setattr("market_radar_data.get_twse_daily", empty_daily)
    monkeypatch.setattr("market_radar_data.get_tpex_daily", empty_daily)

    fake_hist = pd.DataFrame({"Close": [88.0]})
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = fake_hist
    monkeypatch.setattr(stock_data.yf, "Ticker", lambda *_: fake_ticker)

    assert stock_data.get_current_price("6666") == 88.0
