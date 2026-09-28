import pandas as pd
import sqlite3
from pathlib import Path

Path("data").mkdir(exist_ok=True)
DB_PATH = "data/trades.db"

TRADE_COLUMNS = [
    "id", "date", "ticker", "direction", "price", "shares",
    "reason", "exit_reason", "market_condition",
    "stop_loss", "target_price", "estimated_eps",
    "notes", "bench_price_on_date", "created_at"
]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT NOT NULL,
            ticker              TEXT NOT NULL,
            direction           TEXT NOT NULL,
            price               REAL NOT NULL,
            shares              INTEGER NOT NULL,
            reason              TEXT,
            exit_reason         TEXT,
            market_condition    TEXT,
            stop_loss           REAL,
            target_price        REAL,
            estimated_eps       REAL,
            notes               TEXT,
            bench_price_on_date REAL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            user_id             TEXT NOT NULL DEFAULT 'admin'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS catalysts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT NOT NULL,
            event_date   TEXT,
            event_type   TEXT,
            description  TEXT,
            is_done      INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            user_id      TEXT NOT NULL DEFAULT 'admin'
        )
    """)

    # 舊資料庫升級：逐一補欄位
    existing = [r[1] for r in c.execute("PRAGMA table_info(trades)").fetchall()]
    for col, dtype in [
        ("exit_reason",         "TEXT"),
        ("target_price",        "REAL"),
        ("estimated_eps",       "REAL"),
        ("bench_price_on_date", "REAL"),
        ("user_id",             "TEXT NOT NULL DEFAULT 'admin'"),
    ]:
        if col not in existing:
            c.execute(f"ALTER TABLE trades ADD COLUMN {col} {dtype}")

    cat_existing = [r[1] for r in c.execute("PRAGMA table_info(catalysts)").fetchall()]
    if "user_id" not in cat_existing:
        c.execute("ALTER TABLE catalysts ADD COLUMN user_id TEXT NOT NULL DEFAULT 'admin'")

    conn.commit()
    conn.close()


def _select(user_id: str) -> tuple[str, tuple]:
    cols = ", ".join(TRADE_COLUMNS)
    return f"SELECT {cols} FROM trades WHERE user_id=?", (user_id,)


def add_trade(date, ticker, direction, price, shares, reason, exit_reason,
              market_condition, stop_loss, target_price, estimated_eps,
              notes, bench_price_on_date=None, user_id: str = "admin"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if hasattr(date, 'strftime'):
        date = date.strftime('%Y-%m-%d')
    else:
        date = pd.to_datetime(str(date)).strftime('%Y-%m-%d')

    c.execute("""
        INSERT INTO trades
          (date, ticker, direction, price, shares, reason, exit_reason,
           market_condition, stop_loss, target_price, estimated_eps,
           notes, bench_price_on_date, user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (date, ticker.upper(), direction, price, shares,
          reason or None, exit_reason or None, market_condition or None,
          float(stop_loss)      if stop_loss      else None,
          float(target_price)   if target_price   else None,
          float(estimated_eps)  if estimated_eps  else None,
          notes or None, bench_price_on_date, user_id))
    conn.commit()
    conn.close()


def _safe_float(val):
    try:
        v = float(val)
        return v if v == v else None
    except Exception:
        return None


def _safe_int(val):
    try:
        return int(float(val))
    except Exception:
        return 0


def bulk_insert_trades(trade_list, user_id: str = "admin"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for t in trade_list:
        c.execute("""
            INSERT INTO trades
              (date, ticker, direction, price, shares, reason, exit_reason,
               market_condition, stop_loss, target_price, estimated_eps,
               notes, bench_price_on_date, user_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pd.to_datetime(str(t.get("date", ""))).strftime('%Y-%m-%d') if t.get("date") else "",
            str(t.get("ticker", "")).upper(),
            str(t.get("direction", "買入")),
            _safe_float(t.get("price")) or 0,
            _safe_int(t.get("shares")),
            t.get("reason")              or None,
            t.get("exit_reason")         or None,
            t.get("market_condition")    or None,
            _safe_float(t.get("stop_loss")),
            _safe_float(t.get("target_price")),
            _safe_float(t.get("estimated_eps")),
            t.get("notes")               or None,
            _safe_float(t.get("bench_price_on_date")),
            user_id,
        ))
    conn.commit()
    conn.close()


def get_all_trades(user_id: str = "admin"):
    """回傳 sqlite3.Row 的 list：支援 row["date"] 也支援 row[0]，
    不用再靠 TRADE_COLUMNS.index(...) 去查欄位位置。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    sql, params = _select(user_id)
    c.execute(sql + " ORDER BY date DESC", params)
    rows = c.fetchall()
    conn.close()
    return rows


def delete_trade(trade_id, user_id: str = "admin"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM trades WHERE id=? AND user_id=?", (trade_id, user_id))
    conn.commit()
    conn.close()


def update_trade(trade_id, date, ticker, direction, price, shares, reason, exit_reason,
                 market_condition, stop_loss, target_price, estimated_eps, notes,
                 user_id: str = "admin"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE trades SET
            date=?, ticker=?, direction=?, price=?, shares=?,
            reason=?, exit_reason=?, market_condition=?,
            stop_loss=?, target_price=?, estimated_eps=?, notes=?
        WHERE id=? AND user_id=?
    """, (
        date, ticker.upper(), direction, price, shares,
        reason or None, exit_reason or None, market_condition or None,
        float(stop_loss)     if stop_loss     else None,
        float(target_price)  if target_price  else None,
        float(estimated_eps) if estimated_eps else None,
        notes or None,
        trade_id, user_id,
    ))
    conn.commit()
    conn.close()


def _fifo_consume(trades):
    """
    對單一股票的交易紀錄（依 date/id 遞增排序）做 FIFO 配對。
    回傳 (holdings, realized_sells)：
      holdings       剩餘持股 lots，[[price, shares, date, bench_price], ...]
      realized_sells 每一筆賣出交易一筆紀錄（就算完全/部分找不到對應買入也會出現，
                     不會整筆消失），欄位：
                       date, shares          賣出日期／賣出股數（原始紀錄）
                       matched_shares         其中有成功配對到買入成本的股數
                       unmatched_shares       找不到對應買入紀錄的股數（例如帳外庫存、
                                              使用這個 app 之前就持有的部位）
                       sell_price
                       avg_cost               matched_shares 部分的加權平均成本，
                                              matched_shares=0 時為 None
                       realized_pnl           只計算 matched_shares 部分的損益，
                                              unmatched 的部分不會被當成損益（也不會
                                              被當成 0 成本的暴利）

    get_open_positions（目前持股）跟 get_realized_sells（已實現損益，含週報、
    已出清持股）共用這份邏輯，避免兩邊各自算出不一致的成本基礎。
    """
    holdings = []
    realized_sells = []

    for (direction, price, shares, date, bench_px, *_rest, exit_reason) in trades:
        if direction == '買入':
            holdings.append([price, shares, date, bench_px])
        else:
            to_sell = shares
            consumed_cost = 0.0
            consumed_shares = 0
            while to_sell > 0 and holdings:
                lot_price, lot_shares, *_ = holdings[0]
                take = min(lot_shares, to_sell)
                consumed_cost += lot_price * take
                consumed_shares += take
                to_sell -= take
                if take == lot_shares:
                    holdings.pop(0)
                else:
                    holdings[0][1] -= take

            avg_cost = (consumed_cost / consumed_shares) if consumed_shares > 0 else None
            realized_sells.append({
                "date": date, "shares": shares,
                "matched_shares": consumed_shares,
                "unmatched_shares": shares - consumed_shares,
                "sell_price": price, "avg_cost": avg_cost,
                "realized_pnl": (price - avg_cost) * consumed_shares if consumed_shares > 0 else 0.0,
                "exit_reason": exit_reason,
            })

    return holdings, realized_sells


def _trades_by_ticker(user_id: str):
    """回傳 {ticker: [(direction, price, shares, date, bench_px, target_price, stop_loss, estimated_eps, exit_reason), ...]}"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT ticker, direction, price, shares, date,
               bench_price_on_date, target_price, stop_loss, estimated_eps, exit_reason
        FROM trades
        WHERE user_id=?
        ORDER BY ticker, date ASC, id ASC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()

    from collections import defaultdict
    tickers = defaultdict(list)
    for (ticker, direction, price, shares, date, bench_px, tgt, sl, eps, exit_reason) in rows:
        tickers[ticker].append((direction, price, shares, date, bench_px, tgt, sl, eps, exit_reason))
    return tickers


def get_open_positions(user_id: str = "admin"):
    results = []
    for ticker, trades in _trades_by_ticker(user_id).items():
        target_price = stop_loss = estimated_eps = None
        for (direction, price, shares, date, bench_px, tgt, sl, eps, _exit_reason) in trades:
            if direction == '買入':
                if tgt: target_price = tgt
                if sl:  stop_loss = sl
                if eps: estimated_eps = eps

        holdings, _realized = _fifo_consume(trades)
        if not holdings:
            continue

        net_shares = sum(h[1] for h in holdings)
        total_cost = sum(h[0] * h[1] for h in holdings)
        total_buy_shares = net_shares
        first_buy_date = holdings[0][2]

        bench_weighted_cost = sum(h[3] * h[1] for h in holdings if h[3])
        bench_shares_with_price = sum(h[1] for h in holdings if h[3])

        results.append((
            ticker, net_shares, total_cost, total_buy_shares,
            first_buy_date, bench_weighted_cost, bench_shares_with_price,
            target_price, stop_loss, estimated_eps
        ))

    return results


def get_realized_sells(user_id: str = "admin", date_from: str = None, date_to: str = None):
    """
    用 FIFO 配對算出每一筆賣出的已實現損益（跟 get_open_positions 同一套演算法），
    可選擇只回傳某個日期區間內的賣出（例如週報、已出清持股）。

    每一筆賣出都會有一筆紀錄，就算賣出股數在系統裡找不到對應的買入紀錄
    （例如使用這個 app 之前就持有的庫存）也一樣會出現，用 unmatched_shares
    標示「找不到成本的股數」，不會把這部分的賣出金額誤算成利潤。

    回傳 [{"ticker", "date", "shares", "matched_shares", "unmatched_shares",
           "sell_price", "avg_cost", "realized_pnl", "exit_reason"}, ...]
    """
    results = []
    for ticker, trades in _trades_by_ticker(user_id).items():
        _holdings, realized_sells = _fifo_consume(trades)
        for sell in realized_sells:
            if date_from and sell["date"] < str(date_from):
                continue
            if date_to and sell["date"] > str(date_to):
                continue
            results.append({"ticker": ticker, **sell})

    return results


def get_buy_trades_missing_bench(user_id: str = "admin"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, date FROM trades
        WHERE direction='買入'
          AND (bench_price_on_date IS NULL OR bench_price_on_date=0)
          AND user_id=?
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def update_bench_price(trade_id, bench_price):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE trades SET bench_price_on_date=? WHERE id=?", (bench_price, trade_id))
    conn.commit()
    conn.close()


def get_reason_stats(user_id: str = "admin"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT reason, ticker, price, shares, date
        FROM trades
        WHERE direction='買入' AND reason IS NOT NULL AND reason!=''
          AND user_id=?
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_exit_reason_stats(user_id: str = "admin"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT s.ticker, b.price AS buy_price, s.price AS sell_price,
               s.exit_reason, b.date AS buy_date, s.date AS sell_date, s.shares AS sold_shares
        FROM trades s
        JOIN trades b ON s.ticker=b.ticker AND b.direction='買入' AND b.user_id=s.user_id
        WHERE s.direction='賣出' AND s.user_id=?
        ORDER BY s.date DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows
