"""
strategy.py — 載入策略參數

有 strategy_config.py（私人、不 commit）就用它，否則用公開的 strategy_defaults.py。
"""

try:
    from strategy_config import STRATEGY
    SOURCE = "custom"
except ImportError:
    from strategy_defaults import STRATEGY
    SOURCE = "default"


def normalize(value: float, bounds: tuple[float, float]) -> float:
    """把 value 線性映射到 0~100，超出區間的部分截斷。"""
    lo, hi = bounds
    return min(100, max(0, (value - lo) / (hi - lo) * 100))


def first_match(value: float, table: list[tuple], default):
    """table 為 [(門檻, 結果), ...] 由高到低排列，回傳第一個 value ≥ 門檻 的結果。"""
    for threshold, result in table:
        if value >= threshold:
            return result
    return default
