"""
formatting.py
畫面用的格式化/上色 helper + trades_to_df。

這些原本定義在 app.py，然後當參數一路傳進每個 view 的 render()。
搬成獨立模組後，views 直接 import 就好，不用再靠 app.py 手動注入。
"""
import pandas as pd

from database import TRADE_COLUMNS
from i18n import t

TRADE_COL_LABELS = {
    "id": "ID", "date": "日期", "ticker": "股票", "direction": "方向",
    "price": "價格", "shares": "股數", "reason": "買入理由",
    "exit_reason": "賣出理由", "market_condition": "大盤位階",
    "stop_loss": "停損價", "target_price": "目標價",
    "estimated_eps": "預估EPS", "notes": "備註",
    "bench_price_on_date": "當日0050價", "created_at": "建立時間"
}


def fmt_pct(val):
    return f"{val:+.2f}%" if val is not None else "N/A"


def fmt_price(val):
    return f"{val:.2f}" if val is not None else "—"


def color_dir(val):
    # val 可能是資料庫的原文「買入」或顯示用的翻譯（Buy）
    is_buy = val in ("買入", t("買入"))
    return f"color: {'#FF6B00' if is_buy else '#00BFA5'}; font-weight: bold"


def color_pnl(val):
    """台股慣例：正數紅色，負數綠色"""
    try:
        n = float(str(val).replace("%", "").replace("+", "").replace(",", ""))
        return f"color: {'#e53935' if n >= 0 else '#26a69a'}; font-weight: bold"
    except (TypeError, ValueError):
        return ""


def trades_to_df(trades):
    """把 get_all_trades() 結果轉成正確命名的 DataFrame"""
    df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    df = df.rename(columns=TRADE_COL_LABELS)
    for col in ["價格", "停損價", "目標價", "當日0050價"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").map(
            lambda x: f"{x:.2f}" if pd.notna(x) else "")
    df["預估EPS"] = pd.to_numeric(df["預估EPS"], errors="coerce").map(
        lambda x: f"{x:.2f}" if pd.notna(x) and x > 0 else "")
    return df
