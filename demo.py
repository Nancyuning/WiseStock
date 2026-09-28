"""
demo.py — 訪客 Demo 模式

設定環境變數 WISESTOCK_DEMO=1 才會在登入頁出現「以訪客身分瀏覽」按鈕。
訪客使用一組虛構的交易紀錄（demo/demo_trades.csv），所有寫入功能都停用。
沒設定時（例如自己在 NAS 上跑），整個 Demo 功能不會出現。
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

import database

DEMO_USER_ID = "__demo__"
DEMO_TRADES_CSV = Path(__file__).parent / "demo" / "demo_trades.csv"


def demo_enabled() -> bool:
    return os.environ.get("WISESTOCK_DEMO", "").strip().lower() in ("1", "true", "yes")


def demo_user() -> dict:
    return {"username": DEMO_USER_ID, "display_name": "訪客（Demo）", "role": "demo"}


def is_demo(user: dict) -> bool:
    return user.get("role") == "demo"


def ensure_demo_trades() -> None:
    """Demo 帳號沒有資料時（第一次啟動、或雲端重新部署清空了 sqlite），載入範例交易。"""
    if database.get_all_trades(DEMO_USER_ID):
        return
    df = pd.read_csv(DEMO_TRADES_CSV, dtype={"ticker": str})
    df = df.astype(object).where(df.notna(), None)
    database.bulk_insert_trades(df.to_dict(orient="records"), user_id=DEMO_USER_ID)
