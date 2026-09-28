"""
持倉/交易紀錄的邏輯測試 — 不依賴 Streamlit 或網路，用 tmp_path 隔離的 sqlite 檔案跑。
"""


def _add(db, user_id, date, ticker, direction, price, shares, **kw):
    db.add_trade(
        date=date, ticker=ticker, direction=direction, price=price, shares=shares,
        reason=kw.get("reason"), exit_reason=kw.get("exit_reason"),
        market_condition=kw.get("market_condition"), stop_loss=kw.get("stop_loss"),
        target_price=kw.get("target_price"), estimated_eps=kw.get("estimated_eps"),
        notes=kw.get("notes"), user_id=user_id,
    )


def test_trades_are_isolated_per_user(test_db):
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 100, 10)
    _add(test_db, "bob",   "2026-01-02", "2330", "買入", 200, 5)

    assert len(test_db.get_all_trades("alice")) == 1
    assert len(test_db.get_all_trades("bob")) == 1
    assert test_db.get_all_trades("nobody") == []


def test_open_positions_fifo_partial_sell(test_db):
    # 買 100股@10 -> 買 50股@12 -> 賣 120股，FIFO 應先吃掉第一批 100，
    # 再吃掉第二批 20，剩下 30 股成本應該是第二批的價格 12
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 10, 100)
    _add(test_db, "alice", "2026-01-05", "2330", "買入", 12, 50)
    _add(test_db, "alice", "2026-01-10", "2330", "賣出", 15, 120)

    positions = test_db.get_open_positions("alice")
    assert len(positions) == 1

    (ticker, net_shares, total_cost, total_buy_shares,
     first_buy_date, *_rest) = positions[0]

    assert ticker == "2330"
    assert net_shares == 30
    assert total_cost == 12 * 30
    assert total_buy_shares == 30
    assert first_buy_date == "2026-01-05"


def test_realized_sells_fifo_matches_open_positions_cost_basis(test_db):
    # 同一批交易：買 100股@10 -> 買 50股@12 -> 賣 120股
    # get_open_positions 用 FIFO 算剩餘成本，get_realized_sells 也該用同一套邏輯
    # 算出這筆賣出的已實現損益：吃光 100股@10 + 20股@12，均價 (100*10+20*12)/120
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 10, 100)
    _add(test_db, "alice", "2026-01-05", "2330", "買入", 12, 50)
    _add(test_db, "alice", "2026-01-10", "2330", "賣出", 15, 120, exit_reason="達標獲利（到目標價）")

    sells = test_db.get_realized_sells("alice")
    assert len(sells) == 1
    sell = sells[0]
    expected_avg_cost = (100 * 10 + 20 * 12) / 120
    assert sell["ticker"] == "2330"
    assert sell["shares"] == 120
    assert sell["matched_shares"] == 120
    assert sell["unmatched_shares"] == 0
    assert round(sell["avg_cost"], 4) == round(expected_avg_cost, 4)
    assert round(sell["realized_pnl"], 2) == round((15 - expected_avg_cost) * 120, 2)
    assert sell["exit_reason"] == "達標獲利（到目標價）"


def test_realized_sells_reports_unmatched_shares_without_inflating_pnl(test_db):
    """賣出股數超過系統裡記錄的買入股數時（例如用這個 app 之前就持有的庫存），
    找不到成本的那部分不該被當成純利潤——這是 00757 那個真實 bug 的最小重現。"""
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 10, 100)
    _add(test_db, "alice", "2026-02-01", "2330", "賣出", 20, 300)  # 只有 100 股找得到成本

    sells = test_db.get_realized_sells("alice")
    assert len(sells) == 1
    sell = sells[0]
    assert sell["shares"] == 300
    assert sell["matched_shares"] == 100
    assert sell["unmatched_shares"] == 200
    assert sell["avg_cost"] == 10
    assert sell["realized_pnl"] == (20 - 10) * 100  # 只算有成本的 100 股，不是全部 300 股


def test_realized_sells_fully_orphan_sell_has_no_cost_and_zero_pnl(test_db):
    # 完全沒有買入紀錄就賣出（帳外庫存），不該出現任何「利潤」
    _add(test_db, "alice", "2025-09-03", "00757", "賣出", 111.6, 1000)

    sells = test_db.get_realized_sells("alice")
    assert len(sells) == 1
    sell = sells[0]
    assert sell["matched_shares"] == 0
    assert sell["unmatched_shares"] == 1000
    assert sell["avg_cost"] is None
    assert sell["realized_pnl"] == 0.0


def test_realized_sells_filters_by_date_range(test_db):
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 10, 100)
    _add(test_db, "alice", "2026-01-10", "2330", "賣出", 15, 50)   # 這週
    _add(test_db, "alice", "2026-02-01", "2330", "賣出", 20, 50)   # 下個月

    week_sells = test_db.get_realized_sells("alice", date_from="2026-01-06", date_to="2026-01-12")
    assert len(week_sells) == 1
    assert week_sells[0]["sell_price"] == 15
    assert week_sells[0]["shares"] == 50


def test_open_positions_excludes_fully_closed(test_db):
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 10, 100)
    _add(test_db, "alice", "2026-01-10", "2330", "賣出", 15, 100)

    assert test_db.get_open_positions("alice") == []


def test_delete_trade_requires_matching_user(test_db):
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 10, 100)
    trade_id = test_db.get_all_trades("alice")[0]["id"]

    # bob 不能刪 alice 的交易
    test_db.delete_trade(trade_id, user_id="bob")
    assert len(test_db.get_all_trades("alice")) == 1

    test_db.delete_trade(trade_id, user_id="alice")
    assert len(test_db.get_all_trades("alice")) == 0


def test_update_trade_requires_matching_user(test_db):
    _add(test_db, "alice", "2026-01-01", "2330", "買入", 10, 100)
    trade_id = test_db.get_all_trades("alice")[0]["id"]

    test_db.update_trade(
        trade_id=trade_id, date="2026-01-01", ticker="2330", direction="買入",
        price=999, shares=100, reason=None, exit_reason=None,
        market_condition=None, stop_loss=None, target_price=None, estimated_eps=None,
        notes=None, user_id="bob",
    )
    assert float(test_db.get_all_trades("alice")[0]["price"]) == 10

    test_db.update_trade(
        trade_id=trade_id, date="2026-01-01", ticker="2330", direction="買入",
        price=999, shares=100, reason=None, exit_reason=None,
        market_condition=None, stop_loss=None, target_price=None, estimated_eps=None,
        notes=None, user_id="alice",
    )
    assert float(test_db.get_all_trades("alice")[0]["price"]) == 999
