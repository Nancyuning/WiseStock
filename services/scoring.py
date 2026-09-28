"""
services/scoring.py — 個股買賣點評分、水位計算機加減碼分類

純函式、不依賴 Streamlit；所有門檻與配分來自 strategy.STRATEGY。
"""
from __future__ import annotations

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
            return grade
    return grades[-1]


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

    add(f"RSI 未過熱（<{cfg['rsi_max']}）", rsi < cfg["rsi_max"], "rsi_not_hot", f"RSI={rsi:.1f}")
    add(f"RSI 未過冷（>{cfg['rsi_min']}）", rsi > cfg["rsi_min"], "rsi_not_cold", f"RSI={rsi:.1f}")
    add("股價站上 EMA20", cur > ind["ema20"], "above_ema20",
        f"現價{cur:.2f} vs EMA20={ind['ema20']:.2f}")
    add("均線多頭排列（EMA20>EMA60>EMA120）", ind["ema20"] > ind["ema60"] > ind["ema120"], "ema_aligned",
        f"EMA20={ind['ema20']:.1f} EMA60={ind['ema60']:.1f} EMA120={ind['ema120']:.1f}")
    add("近60日跑贏0050（RS>0）", rs is not None and rs > 0, "rs_positive",
        f"RS={rs:+.1f}%" if rs is not None else "資料不足")
    add(f"距52週高點有空間（<{cfg['high_gap_pct']}%）", ind["pfh"] < cfg["high_gap_pct"], "room_to_high",
        f"距高點{ind['pfh']:.1f}%")
    add(f"布林通道位置適中（{cfg['bb_low']}%~{cfg['bb_high']}%）",
        cfg["bb_low"] < ind["bbpct"] < cfg["bb_high"], "bb_middle", f"布林位置{ind['bbpct']:.0f}%")

    total = sum(r["得分"] for r in rows)
    grade, color = _grade(total, STRATEGY["stock_score"]["buy_grades"], BUY_GRADES)
    return {"rows": rows, "total": total, "max": sum(r["滿分"] for r in rows), "grade": grade, "color": color}


def score_sell(ind: dict) -> dict:
    """參數同 score_buy，回傳 {"rows", "total", "max", "grade", "color"}"""
    cfg, pts = STRATEGY["stock_score"]["sell"], STRATEGY["stock_score"]["sell"]["points"]
    rsi, cur, rs = ind["rsi"], ind["cur"], ind["rs"]
    rows = []

    def add(label, cond, key, detail):
        rows.append({"條件": label, "觸發": "⚠️ 是" if cond else "✅ 否",
                     "風險分": pts[key] if cond else 0, "滿分": pts[key], "說明": detail})

    add(f"RSI 過熱（>{cfg['rsi_hot']}）", rsi > cfg["rsi_hot"], "rsi_hot", f"RSI={rsi:.1f}")
    add(f"接近52週高點（距高點<{abs(cfg['near_high_pct'])}%）", ind["pfh"] > cfg["near_high_pct"], "near_high",
        f"距高點{ind['pfh']:.1f}%")
    add("短均線跌破長均線（EMA20<EMA60）", ind["ema20"] < ind["ema60"], "ema_cross_down",
        f"EMA20={ind['ema20']:.1f} EMA60={ind['ema60']:.1f}")
    add(f"布林上緣（>{cfg['bb_upper']}%）", ind["bbpct"] > cfg["bb_upper"], "bb_upper", f"布林位置{ind['bbpct']:.0f}%")
    add("近60日跑輸0050（RS<0）", rs is not None and rs < 0, "rs_negative",
        f"RS={rs:+.1f}%" if rs is not None else "資料不足")
    add("股價跌破 EMA20", cur < ind["ema20"], "below_ema20", f"現價{cur:.2f} vs EMA20={ind['ema20']:.2f}")

    total = sum(r["風險分"] for r in rows)
    grade, color = _grade(total, STRATEGY["stock_score"]["sell_grades"], SELL_GRADES)
    return {"rows": rows, "total": total, "max": sum(r["滿分"] for r in rows), "grade": grade, "color": color}


def classify_rebalance(sig: dict, diff_val: float) -> tuple[str, list[str]]:
    """
    依三燈號與水位差距，把一檔持股分到 "trim"（減碼）/ "entry"（加碼）/ "hold"（續抱觀察）。
    sig: check_stock_signals() 的結果；diff_val: 建議持股市值 − 目前持股市值
    回傳 (分類, 理由列表)
    """
    cfg      = STRATEGY["rebalance"]
    h        = sig["raw"]
    momentum = sig.get("momentum_label", "")
    timing   = sig.get("timing_label", "")
    volume   = sig.get("volume_label", "")
    cur_p    = h.get("current_price") or 0
    atr_stop = h.get("atr_trail_stop")

    trim, hold = [], []
    if momentum in cfg["trim_momentum"]: trim.append(f"動能：{momentum}")
    if timing in cfg["trim_timing"]:     trim.append(f"時機：{timing}")
    if cfg["trim_on_atr_break"] and atr_stop is not None and 0 < cur_p < atr_stop:
        trim.append(f"已跌破 ATR 停利參考 {atr_stop:.2f} 元")
    if volume in cfg["trim_volume"]:     trim.append("量價背離，OBV 警示")
    if cfg["hold_if_only_momentum_weak"] and trim == [f"動能：{momentum}"] and diff_val >= 0:
        hold, trim = trim + ["水位未超配，暫續抱觀察"], []

    if trim:
        return "trim", trim
    if (momentum in cfg["entry_momentum"] and timing in cfg["entry_timing"]
            and volume in cfg["entry_volume"] and diff_val > 0):
        entry = [f"動能：{momentum}", f"時機：{timing}"]
        if volume == "價量齊揚":
            entry.append("量價齊揚佐證")
        return "entry", entry
    if not hold:
        hold = ["水位已足" if not diff_val > 0 else
                "超買區，等回踩再加" if timing == "超買謹慎" else "條件尚未全部對齊，等待"]
    return "hold", hold
