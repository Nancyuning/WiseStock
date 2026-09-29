"""
services/scoring.py — 個股買賣點評分

純函式、不依賴 Streamlit；所有門檻與配分來自 strategy.STRATEGY。
畫面文字經 i18n.t() 翻譯；rows 的 dict key（條件/結果/得分…）維持中文，畫面再用 t_cols 翻欄名。
"""
from __future__ import annotations

from i18n import t
from strategy import STRATEGY

BUY_GRADES = [
    ("A　條件優秀", "#FFD700"),
    ("B　條件尚可", "#f39c12"),
    ("C　條件普通", "#e67e22"),
    ("D　條件不佳", "#9e9e9e"),
]
SELL_GRADES = [
    ("🟢 高風險　多個賣點訊號觸發", "#26a69a"),
    ("🟡 中風險　部分賣點條件出現", "#f1c40f"),
    ("🟠 低風險　少數條件觸發", "#f39c12"),
    ("🔴 現在不是明顯賣點", "#ef5350"),
]


def _grade(total: float, cutoffs: tuple, grades: list[tuple]) -> tuple[str, str]:
    for cutoff, grade in zip(cutoffs, grades):
        if total >= cutoff:
            return t(grade[0]), grade[1]
    return t(grades[-1][0]), grades[-1][1]


def score_buy(ind: dict) -> dict:
    """
    ind: cur, ema20, ema60, ema120, rsi, pfh(距 52 週高點 %), bbpct(布林位置 %), rs(可為 None)
    回傳 {"rows": [...], "total", "max", "grade", "color"}
    """
    cfg, pts = STRATEGY["stock_score"]["buy"], STRATEGY["stock_score"]["buy"]["points"]
    rsi, cur, rs = ind["rsi"], ind["cur"], ind["rs"]
    rows = []

    def add(label, cond, key, detail):
        rows.append({"條件": label, "結果": "✅" if cond else "❌",
                     "得分": pts[key] if cond else 0, "滿分": pts[key], "說明": detail})

    add(t("RSI 未過熱（<{v}）", v=cfg["rsi_max"]), rsi < cfg["rsi_max"], "rsi_not_hot", f"RSI={rsi:.1f}")
    add(t("RSI 未過冷（>{v}）", v=cfg["rsi_min"]), rsi > cfg["rsi_min"], "rsi_not_cold", f"RSI={rsi:.1f}")
    add(t("股價站上 EMA20"), cur > ind["ema20"], "above_ema20",
        t("現價{cur:.2f} vs EMA20={ema20:.2f}", cur=cur, ema20=ind["ema20"]))
    add(t("均線多頭排列（EMA20>EMA60>EMA120）"), ind["ema20"] > ind["ema60"] > ind["ema120"], "ema_aligned",
        f"EMA20={ind['ema20']:.1f} EMA60={ind['ema60']:.1f} EMA120={ind['ema120']:.1f}")
    add(t("近60日跑贏0050（RS>0）"), rs is not None and rs > 0, "rs_positive",
        f"RS={rs:+.1f}%" if rs is not None else t("資料不足"))
    add(t("距52週高點有空間（<{v}%）", v=cfg["high_gap_pct"]), ind["pfh"] < cfg["high_gap_pct"], "room_to_high",
        t("距高點{pct:.1f}%", pct=ind["pfh"]))
    add(t("布林通道位置適中（{lo}%~{hi}%）", lo=cfg["bb_low"], hi=cfg["bb_high"]),
        cfg["bb_low"] < ind["bbpct"] < cfg["bb_high"], "bb_middle", t("布林位置{pct:.0f}%", pct=ind["bbpct"]))

    total = sum(r["得分"] for r in rows)
    grade, color = _grade(total, STRATEGY["stock_score"]["buy_grades"], BUY_GRADES)
    return {"rows": rows, "total": total, "max": sum(r["滿分"] for r in rows), "grade": grade, "color": color}


def score_sell(ind: dict) -> dict:
    """參數同 score_buy，回傳 {"rows", "total", "max", "grade", "color"}"""
    cfg, pts = STRATEGY["stock_score"]["sell"], STRATEGY["stock_score"]["sell"]["points"]
    rsi, cur, rs = ind["rsi"], ind["cur"], ind["rs"]
    rows = []

    def add(label, cond, key, detail):
        rows.append({"條件": label, "觸發": t("⚠️ 是") if cond else t("✅ 否"),
                     "風險分": pts[key] if cond else 0, "滿分": pts[key], "說明": detail})

    add(t("RSI 過熱（>{v}）", v=cfg["rsi_hot"]), rsi > cfg["rsi_hot"], "rsi_hot", f"RSI={rsi:.1f}")
    add(t("接近52週高點（距高點<{v}%）", v=abs(cfg["near_high_pct"])), ind["pfh"] > cfg["near_high_pct"], "near_high",
        t("距高點{pct:.1f}%", pct=ind["pfh"]))
    add(t("短均線跌破長均線（EMA20<EMA60）"), ind["ema20"] < ind["ema60"], "ema_cross_down",
        f"EMA20={ind['ema20']:.1f} EMA60={ind['ema60']:.1f}")
    add(t("布林上緣（>{v}%）", v=cfg["bb_upper"]), ind["bbpct"] > cfg["bb_upper"], "bb_upper",
        t("布林位置{pct:.0f}%", pct=ind["bbpct"]))
    add(t("近60日跑輸0050（RS<0）"), rs is not None and rs < 0, "rs_negative",
        f"RS={rs:+.1f}%" if rs is not None else t("資料不足"))
    add(t("股價跌破 EMA20"), cur < ind["ema20"], "below_ema20",
        t("現價{cur:.2f} vs EMA20={ema20:.2f}", cur=cur, ema20=ind["ema20"]))

    total = sum(r["風險分"] for r in rows)
    grade, color = _grade(total, STRATEGY["stock_score"]["sell_grades"], SELL_GRADES)
    return {"rows": rows, "total": total, "max": sum(r["滿分"] for r in rows), "grade": grade, "color": color}
