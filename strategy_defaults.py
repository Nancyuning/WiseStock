"""
strategy_defaults.py — 公開版的策略參數（一般教科書等級的預設值）

所有「評分權重、門檻、加減碼規則」都集中在這裡，程式邏輯不寫死任何數字。
想套用自己調整過的參數：複製這份為 strategy_config.py 再修改，
strategy_config.py 已被 .gitignore 排除，不會被 commit。

結構說明
  market_risk  水位計算機：0050 風險分數 → 震盪機率 → 建議持股水位
  health       個股健康診斷：量價、KD、ATR 等門檻
  signals      三燈號（動能 / 進場時機 / 量價）的 RSI 門檻
  stock_score  個股分析頁：買點 / 賣點評分的條件、配分與等級門檻
  rebalance    水位計算機：哪些燈號組合算「減碼 / 加碼」
"""

STRATEGY = {
    "market_risk": {
        # 各指標線性正規化到 0~100 的區間 (低於下限=0, 高於上限=100)
        "normalize": {
            "rsi":  (50, 80),   # 0050 RSI(14)
            "bias": (0, 10),    # 0050 季線乖離率 %
            "vol":  (10, 30),   # 20 日年化波動率 %
            "vix":  (12, 30),   # VIX
        },
        "weights": {"rsi": 0.25, "bias": 0.25, "vol": 0.25, "vix": 0.25},
        # 震盪機率 ≥ 門檻 → 預估震盪倒數天數（由高到低排列）
        "osc_days": [(75, 10), (50, 30), (25, 60)],
        "osc_days_default": 90,
        # 建議持股水位 = base − 震盪機率 × slope，再夾在 [min, max]
        "ratio": {"base": 90, "slope": 0.5, "min": 40, "max": 90},
        # 季線乖離 ≥ 門檻 → 大盤現況標籤（由高到低排列）
        "market_label": [
            (10, "過熱（乖離過大）"),
            (0, "多頭延續（順勢區）"),
            (-10, "回測支撐（逢低佈局）"),
        ],
        "market_label_default": "超跌（長線浮現）",
        # 儀表板顏色分級
        "gauge": {"high": 60, "mid": 35},
    },
    "health": {
        "exhaustion_vol_ratio": 0.7,   # 價創新高但 5 日均量 < 20 日均量 × 此值 → 動能衰竭
        "breakdown_vol_ratio":  1.5,   # 跌破均線且當日量 > 20 日均量 × 此值 → 帶量跌破
        "kd_oversold":   20,
        "kd_overbought": 80,
        "pullback_bias_max": 3.0,      # 多頭中距 MA20 0~X% → 回測支撐
        "atr_multiplier": 3,           # 停利參考 = 近 60 日高點 − N × ATR14
    },
    "signals": {
        "rsi_overheat": 75,            # RSI 超過 → 過熱不追
        "golden_cross_rsi_max": 65,    # KD 黃金交叉且 RSI 低於此值 → 建議加碼
    },
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
    "rebalance": {
        "trim_momentum": ["盤整/弱勢"],
        "trim_timing":   ["KD死叉出場"],
        "trim_volume":   ["誘多背離"],
        "trim_on_atr_break": True,
        # 只有「動能轉弱」一個減碼理由、且水位未超配時，改列續抱觀察
        "hold_if_only_momentum_weak": False,
        "entry_momentum": ["強力噴發", "趨勢偏多"],
        "entry_timing":   ["建議加碼"],
        "entry_volume":   ["價量齊揚", "量能持平"],
    },
}
