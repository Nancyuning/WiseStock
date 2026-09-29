"""
strategy_defaults.py — 公開版的策略參數（一般教科書等級的預設值）

所有「評分權重、門檻、加減碼規則」都集中在這裡，程式邏輯不寫死任何數字。
想套用自己調整過的參數：複製這份為 strategy_config.py 再修改，
strategy_config.py 已被 .gitignore 排除，不會被 commit。

結構說明
  stock_score  個股分析頁：買點 / 賣點評分的條件、配分與等級門檻
"""

STRATEGY = {
    "stock_score": {
        "buy": {
            "rsi_max": 70, "rsi_min": 30,
            "high_gap_pct": -10,       # 距 52 週高點低於此值才算有空間
            "bb_low": 20, "bb_high": 80,
            "points": {
                "rsi_not_hot": 15, "rsi_not_cold": 15, "above_ema20": 15,
                "ema_aligned": 15, "rs_positive": 15, "room_to_high": 15,
                "bb_middle": 10,
            },
        },
        "buy_grades": (75, 50, 25),    # A / B / C 的最低分，以下為 D
        "sell": {
            "rsi_hot": 70,
            "near_high_pct": -3,       # 距 52 週高點高於此值算接近高點
            "bb_upper": 90,
            "points": {
                "rsi_hot": 20, "near_high": 15, "ema_cross_down": 20,
                "bb_upper": 15, "rs_negative": 15, "below_ema20": 15,
            },
        },
        "sell_grades": (60, 40, 20),   # 高 / 中 / 低風險的最低分
    },
}
