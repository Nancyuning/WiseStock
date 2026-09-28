"""
services/trade_service.py 的測試 — 用假的 fetch_bench_price，不打真的網路。
"""
import pandas as pd
import pytest

from services import trade_service as ts


def _fake_bench_price(ticker, date):
    return 100.0


@pytest.mark.parametrize("ticker,expected", [
    ("2330", True),
    ("0050", True),
    ("00981A", True),
    ("", False),
    ("ABC", False),
    ("23301234", False),
])
def test_is_valid_ticker(ticker, expected):
    assert ts.is_valid_ticker(ticker) is expected


def test_validate_manual_trade_reports_all_errors():
    errors = ts.validate_manual_trade(ticker="", price=0, shares=0)
    assert "請輸入股票代號" in errors
    assert "請輸入成交價格" in errors
    assert "請輸入股數" in errors


def test_validate_manual_trade_ok():
    assert ts.validate_manual_trade(ticker="2330", price=100, shares=10) == []


def test_create_trade_rejects_invalid_input_without_writing(test_db):
    result = ts.create_trade(
        date="2026-01-01", ticker="", direction="買入", price=100, shares=10,
        user_id="alice", fetch_bench_price=_fake_bench_price,
    )
    assert result["ok"] is False
    assert test_db.get_all_trades("alice") == []


def test_create_trade_buy_fetches_bench_price_and_forward_pe(test_db):
    result = ts.create_trade(
        date="2026-01-01", ticker="2330", direction="買入", price=100, shares=10,
        estimated_eps=10, user_id="alice", fetch_bench_price=_fake_bench_price,
    )
    assert result["ok"] is True
    assert result["bench_price"] == 100.0
    assert result["forward_pe"] == 10.0
    assert len(test_db.get_all_trades("alice")) == 1


def test_create_trade_sell_does_not_fetch_bench_price(test_db):
    calls = []

    def tracking_fetch(ticker, date):
        calls.append((ticker, date))
        return 100.0

    result = ts.create_trade(
        date="2026-01-01", ticker="2330", direction="賣出", price=100, shares=10,
        user_id="alice", fetch_bench_price=tracking_fetch,
    )
    assert result["ok"] is True
    assert result["bench_price"] is None
    assert calls == []


def test_validate_csv_rows_flags_missing_columns():
    df = pd.DataFrame({"date": ["2026-01-01"], "ticker": ["2330"]})
    result = ts.validate_csv_rows(df)
    assert result["missing_cols"] == {"direction", "price", "shares"}
    assert result["clean"] is None


def test_validate_csv_rows_flags_bad_rows():
    df = pd.DataFrame({
        "date":      ["2026-01-01", "2026-01-02", "2026-01-03"],
        "ticker":    ["2330", "BADTICKER", "2330"],
        "direction": ["買入", "買入", "持有"],
        "price":     [100, 50, 0],
        "shares":    [10, 10, 10],
    })
    result = ts.validate_csv_rows(df)
    assert result["missing_cols"] == set()
    assert len(result["bad_ticker"]) == 1
    assert len(result["bad_direction"]) == 1
    assert len(result["bad_price"]) == 1


def test_import_csv_trades_auto_fills_bench_price(test_db):
    df = pd.DataFrame({
        "date": ["2026-01-01"], "ticker": ["2330"], "direction": ["買入"],
        "price": [100], "shares": [10],
    })
    count = ts.import_csv_trades(df, user_id="alice", fetch_bench_price=_fake_bench_price)
    assert count == 1
    trades = test_db.get_all_trades("alice")
    assert trades[0]["bench_price_on_date"] == 100.0


def test_import_csv_trades_progress_callback(test_db):
    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02"], "ticker": ["2330", "2317"],
        "direction": ["買入", "買入"], "price": [100, 50], "shares": [10, 20],
    })
    progress_calls = []
    ts.import_csv_trades(
        df, user_id="alice", fetch_bench_price=_fake_bench_price,
        on_progress=lambda done, total: progress_calls.append((done, total)),
    )
    assert progress_calls == [(1, 2), (2, 2)]
