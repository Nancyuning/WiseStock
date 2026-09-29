"""
services/scoring.py（買賣點評分）與 strategy.py 的測試。
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


def test_score_labels_are_translated_in_english(monkeypatch):
    import i18n
    monkeypatch.setattr(i18n, "get_lang", lambda: "en")
    result = scoring.score_buy(_ind())
    assert result["grade"].startswith("A") and "Excellent" in result["grade"]
    assert result["rows"][0]["條件"] == "RSI not overbought (<70)"
    sell = scoring.score_sell(_ind(rsi=85))
    assert sell["rows"][0]["觸發"] == "⚠️ Yes"
