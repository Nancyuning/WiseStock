"""
services/trade_service.py
交易紀錄的驗證與業務邏輯 — 從 views/trades.py 抽出來，
不依賴 Streamlit，可以直接用 pytest 測試。

`fetch_bench_price` 用參數注入（預設是真的打 yfinance 的 get_price_on_date），
測試時可以換成假函式，不必真的連網路。
"""
from __future__ import annotations

import re

import pandas as pd

import database
from stock_data import calc_forward_pe, get_price_on_date

REQUIRED_CSV_COLUMNS = {"date", "ticker", "direction", "price", "shares"}
VALID_DIRECTIONS = {"買入", "賣出"}
NUMERIC_CSV_COLUMNS = ["price", "stop_loss", "target_price", "estimated_eps"]


def is_valid_ticker(ticker: str) -> bool:
    return bool(re.match(r"^[0-9]{2,6}[A-Za-z]?$", str(ticker).strip()))


def validate_manual_trade(ticker: str, price: float, shares: int) -> list[str]:
    """回傳錯誤訊息列表，空 list 代表驗證通過。"""
    errors = []
    if not ticker or not str(ticker).strip():
        errors.append("請輸入股票代號")
    if price is None or price <= 0:
        errors.append("請輸入成交價格")
    if shares is None or shares <= 0:
        errors.append("請輸入股數")
    return errors


def create_trade(
    *, date, ticker, direction, price, shares,
    reason=None, exit_reason=None, market_condition=None,
    stop_loss=None, target_price=None, estimated_eps=None,
    notes=None, user_id: str = "admin",
    fetch_bench_price=get_price_on_date,
) -> dict:
    """
    驗證 + (買入時)查當日 0050 價 + 寫入 DB。
    回傳 {"ok", "errors", "ticker", "total", "bench_price", "forward_pe"}。
    """
    errors = validate_manual_trade(ticker, price, shares)
    if errors:
        return {"ok": False, "errors": errors}

    ticker = ticker.strip().upper()
    bench_price = fetch_bench_price("0050", str(date)) if direction == "買入" else None

    database.add_trade(
        date=str(date), ticker=ticker, direction=direction, price=price, shares=shares,
        reason=reason, exit_reason=exit_reason, market_condition=market_condition,
        stop_loss=stop_loss if stop_loss and stop_loss > 0 else None,
        target_price=target_price if target_price and target_price > 0 else None,
        estimated_eps=estimated_eps if estimated_eps and estimated_eps > 0 else None,
        notes=notes, bench_price_on_date=bench_price, user_id=user_id,
    )

    forward_pe = None
    if direction == "買入" and estimated_eps and estimated_eps > 0:
        forward_pe = calc_forward_pe(price, estimated_eps)

    return {
        "ok": True, "errors": [],
        "ticker": ticker, "total": price * shares,
        "bench_price": bench_price, "forward_pe": forward_pe,
    }


def normalize_csv_trades(df: pd.DataFrame) -> pd.DataFrame:
    """數值/日期/代號清理，回傳新的 DataFrame（不修改傳入的 df）。"""
    df = df.copy()
    for col in NUMERIC_CSV_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"].astype(str), errors="coerce").dt.strftime("%Y-%m-%d")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df


def validate_csv_rows(df: pd.DataFrame) -> dict:
    """
    驗證上傳的交易 CSV。回傳：
      missing_cols   缺少的必要欄位（set，非空代表整份 CSV 不能用）
      clean          清理過的 DataFrame（missing_cols 非空時為 None）
      bad_direction  direction 不是「買入」/「賣出」的列
      bad_ticker     代號格式看起來有誤的列（僅警告，不阻擋匯入）
      bad_price      price 是空值或 <=0 的列
    """
    missing_cols = REQUIRED_CSV_COLUMNS - set(df.columns)
    if missing_cols:
        return {
            "missing_cols": missing_cols, "clean": None,
            "bad_direction": None, "bad_ticker": None, "bad_price": None,
        }

    clean = normalize_csv_trades(df)
    return {
        "missing_cols": missing_cols,
        "clean": clean,
        "bad_direction": clean[~clean["direction"].isin(VALID_DIRECTIONS)],
        "bad_ticker": clean[~clean["ticker"].apply(is_valid_ticker)],
        "bad_price": clean[clean["price"].isna() | (clean["price"] <= 0)],
    }


def import_csv_trades(
    df: pd.DataFrame, user_id: str = "admin", auto_bench: bool = True,
    fetch_bench_price=get_price_on_date, on_progress=None,
) -> int:
    """批次寫入交易紀錄，回傳成功匯入的筆數。on_progress(done, total) 供畫面顯示進度。"""
    trade_list = df.to_dict(orient="records")
    total = len(trade_list)
    for i, t in enumerate(trade_list):
        if auto_bench and str(t.get("direction")) == "買入" and not t.get("bench_price_on_date"):
            t["bench_price_on_date"] = fetch_bench_price("0050", str(t.get("date", "")))
        if on_progress:
            on_progress(i + 1, total)

    database.bulk_insert_trades(trade_list, user_id=user_id)
    return total
