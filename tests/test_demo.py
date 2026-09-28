import pandas as pd

import demo


def test_demo_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WISESTOCK_DEMO", raising=False)
    assert not demo.demo_enabled()


def test_demo_enabled_by_env(monkeypatch):
    for value in ("1", "true", "YES"):
        monkeypatch.setenv("WISESTOCK_DEMO", value)
        assert demo.demo_enabled()
    monkeypatch.setenv("WISESTOCK_DEMO", "0")
    assert not demo.demo_enabled()


def test_demo_user_is_not_admin():
    user = demo.demo_user()
    assert demo.is_demo(user)
    assert user["role"] != "admin"


def test_ensure_demo_trades_seeds_once(test_db):
    expected = len(pd.read_csv(demo.DEMO_TRADES_CSV))
    demo.ensure_demo_trades()
    demo.ensure_demo_trades()
    assert len(test_db.get_all_trades(demo.DEMO_USER_ID)) == expected


def test_demo_trades_are_isolated_from_real_users(test_db):
    demo.ensure_demo_trades()
    assert test_db.get_all_trades("admin") == []


def test_demo_trades_produce_positions_and_realized_pnl(test_db):
    demo.ensure_demo_trades()
    assert test_db.get_open_positions(demo.DEMO_USER_ID)
    assert test_db.get_realized_sells(demo.DEMO_USER_ID)
    assert test_db.get_buy_trades_missing_bench(demo.DEMO_USER_ID) == []
