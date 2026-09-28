"""
services/scoring.py 與 strategy.py 的測試。
一律使用公開的 strategy_defaults，結果不受本機有沒有 strategy_config.py 影響。
"""
import copy

import pytest

import strategy
import strategy_defaults
from services import scoring


@pytest.fixture(autouse=True)
def default_strategy(monkeypatch):
    cfg = copy.deepcopy(strategy_defaults.STRATEGY)
    monkeypatch.setattr(scoring, "STRATEGY", cfg)
    return cfg


def _ind(**kw):
    base = dict(cur=100, ema20=95, ema60=90, ema120=85, rsi=50, pfh=-20, bbpct=50, rs=5)
    base.update(kw)
    return base


def test_normalize_clamps_to_0_100():
    assert strategy.normalize(5, (10, 20)) == 0
    assert strategy.normalize(15, (10, 20)) == 50
    assert strategy.normalize(99, (10, 20)) == 100


def test_first_match_picks_first_threshold_reached():
    table = [(70, "high"), (40, "mid")]
    assert strategy.first_match(80, table, "low") == "high"
    assert strategy.first_match(40, table, "low") == "mid"
    assert strategy.first_match(10, table, "low") == "low"


def test_market_risk_weights_sum_to_one():
    assert sum(strategy_defaults.STRATEGY["market_risk"]["weights"].values()) == pytest.approx(1)


def test_score_buy_all_conditions_met_gets_full_marks(default_strategy):
    result = scoring.score_buy(_ind())
    assert result["total"] == result["max"] == 100
    assert result["grade"].startswith("A")


def test_score_buy_uses_configured_points(default_strategy):
    default_strategy["stock_score"]["buy"]["points"]["rs_positive"] = 40
    with_rs = scoring.score_buy(_ind(rs=5))["total"]
    without_rs = scoring.score_buy(_ind(rs=-5))["total"]
    assert with_rs - without_rs == 40


def test_score_buy_handles_missing_rs():
    rows = scoring.score_buy(_ind(rs=None))["rows"]
    rs_row = next(r for r in rows if "0050" in r["條件"])
    assert rs_row["得分"] == 0 and rs_row["說明"] == "資料不足"


def test_score_sell_overheated_near_high_is_high_risk():
    result = scoring.score_sell(_ind(rsi=85, pfh=-1, bbpct=95, ema20=80, cur=75, rs=-3))
    assert result["total"] == result["max"]
    assert "高風險" in result["grade"]


def _sig(momentum="趨勢偏多", timing="建議加碼", volume="價量齊揚", cur=100, atr_stop=None):
    return {"momentum_label": momentum, "timing_label": timing, "volume_label": volume,
            "raw": {"current_price": cur, "atr_trail_stop": atr_stop}}


def test_rebalance_entry_when_all_signals_align_and_underweight():
    kind, reasons = scoring.classify_rebalance(_sig(), diff_val=10_000)
    assert kind == "entry" and "量價齊揚佐證" in reasons


def test_rebalance_no_entry_when_already_fully_invested():
    kind, reasons = scoring.classify_rebalance(_sig(), diff_val=-1)
    assert kind == "hold" and reasons == ["水位已足"]


def test_rebalance_trim_on_atr_break():
    kind, reasons = scoring.classify_rebalance(_sig(cur=90, atr_stop=95), diff_val=10_000)
    assert kind == "trim" and any("ATR" in r for r in reasons)


def test_rebalance_hold_if_only_momentum_weak_is_configurable(default_strategy):
    sig = _sig(momentum="盤整/弱勢", timing="觀察等待", volume="量能持平")
    default_strategy["rebalance"]["hold_if_only_momentum_weak"] = False
    assert scoring.classify_rebalance(sig, diff_val=0)[0] == "trim"
    default_strategy["rebalance"]["hold_if_only_momentum_weak"] = True
    assert scoring.classify_rebalance(sig, diff_val=0)[0] == "hold"


def test_private_config_has_same_structure_as_defaults():
    """strategy_config.py（若存在）必須跟公開預設值有相同的鍵，避免漏設參數。"""
    try:
        import strategy_config
    except ImportError:
        pytest.skip("本機沒有 strategy_config.py")

    def keys(d, prefix=""):
        out = set()
        for k, v in d.items():
            out.add(prefix + k)
            if isinstance(v, dict):
                out |= keys(v, prefix + k + ".")
        return out

    assert keys(strategy_config.STRATEGY) == keys(strategy_defaults.STRATEGY)
