"""
market_radar_db.py
集保歷史資料 SQLite 模組
─────────────────────────────────────────────────────────
職責：
  - 建立與維護 .cache_radar/market_radar.db
  - 提供 tdcc_history / tdcc_watchlist 兩張 table 的 CRUD
  - 不依賴 market_radar_data.py，可獨立 import

Table 設計：
  tdcc_history
    (stock_id, date, level) PRIMARY KEY
    people  INTEGER  — 該級距股東人數
    unit    INTEGER  — 張數（已 ÷1000）
    percent REAL     — 個股內部比例（非全市場），用 unit/total_unit 重算

  tdcc_watchlist
    stock_id     TEXT PRIMARY KEY
    last_updated TEXT  — ISO date 'YYYY-MM-DD'，上次成功寫入 DB 的日期
    first_seen   TEXT  — 第一次被加入的日期
─────────────────────────────────────────────────────────
"""

from __future__ import annotations
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

import pandas as pd

# ── DB 路徑（統一放在 data/ 資料夾，不易誤刪）────────────
DB_PATH = Path("data") / "market_radar.db"
DB_PATH.parent.mkdir(exist_ok=True)

# ── Thread-local connection pool ─────────────────────────
_local = threading.local()
_init_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """
    每個 thread 各自維護一條 sqlite3 連線（thread-local）。
    WAL mode 讓多執行緒讀不阻塞寫。
    """
    if not getattr(_local, "conn", None):
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


@contextmanager
def _tx():
    """簡單的 transaction context manager，自動 commit / rollback。"""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ══════════════════════════════════════════════════════════
# 初始化
# ══════════════════════════════════════════════════════════

def init_db() -> None:
    """
    建立 tables（冪等，可重複呼叫）。
    app 啟動時呼叫一次即可。
    """
    with _init_lock:
        with _tx() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tdcc_history (
                    stock_id  TEXT    NOT NULL,
                    date      TEXT    NOT NULL,
                    level     INTEGER NOT NULL,
                    people    INTEGER DEFAULT 0,
                    unit      INTEGER DEFAULT 0,
                    percent   REAL    DEFAULT 0.0,
                    PRIMARY KEY (stock_id, date, level)
                );

                CREATE INDEX IF NOT EXISTS idx_tdcc_stock_date
                    ON tdcc_history (stock_id, date);

                CREATE TABLE IF NOT EXISTS tdcc_watchlist (
                    user_id      TEXT NOT NULL,
                    stock_id     TEXT NOT NULL,
                    last_updated TEXT,
                    first_seen   TEXT,
                    PRIMARY KEY (user_id, stock_id)
                );
            """)

            # 舊版 watchlist（stock_id 單一 PK）升級為複合 PK
            wl_cols = [r[1] for r in conn.execute("PRAGMA table_info(tdcc_watchlist)").fetchall()]
            if "user_id" not in wl_cols:
                conn.executescript("""
                    ALTER TABLE tdcc_watchlist RENAME TO tdcc_watchlist_old;
                    CREATE TABLE tdcc_watchlist (
                        user_id      TEXT NOT NULL,
                        stock_id     TEXT NOT NULL,
                        last_updated TEXT,
                        first_seen   TEXT,
                        PRIMARY KEY (user_id, stock_id)
                    );
                    INSERT INTO tdcc_watchlist (user_id, stock_id, last_updated, first_seen)
                    SELECT 'admin', stock_id, last_updated, first_seen FROM tdcc_watchlist_old;
                    DROP TABLE tdcc_watchlist_old;
                """)


# ══════════════════════════════════════════════════════════
# tdcc_history 寫入
# ══════════════════════════════════════════════════════════

def upsert_tdcc_week(stock_id: str, records: list[dict]) -> int:
    """
    將一支股票某週的集保級距資料寫入 DB（INSERT OR REPLACE）。

    records 格式（list of dict）：
        [{"date": "2025-04-24", "level": 12,
          "people": 3210, "unit": 58000, "percent": 42.31}, ...]

    date 接受 "YYYY-MM-DD" 或 "YYYYMMDD"，內部統一存 "YYYY-MM-DD"。

    回傳成功寫入筆數。
    """
    if not records:
        return 0

    sid = str(stock_id).strip().upper()
    rows = []
    for r in records:
        raw_date = str(r.get("date", "")).strip()
        # 統一轉成 YYYY-MM-DD
        if len(raw_date) == 8 and raw_date.isdigit():
            iso_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        else:
            try:
                iso_date = pd.to_datetime(raw_date, errors="coerce").strftime("%Y-%m-%d")
            except Exception:
                continue
        if iso_date == "NaT" or not iso_date:
            continue

        rows.append((
            sid,
            iso_date,
            int(r.get("level",   0)),
            int(r.get("people",  0)),
            int(r.get("unit",    0)),
            float(r.get("percent", 0.0)),
        ))

    if not rows:
        return 0

    with _tx() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO tdcc_history
               (stock_id, date, level, people, unit, percent)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def upsert_tdcc_batch(df: pd.DataFrame) -> int:
    """
    批次寫入全市場集保資料（_get_tdcc_full 下載完後呼叫）。

    df 需含欄位：stock_id, date, level, people, unit
    percent 會在這裡按個股重算（unit / stock_total_unit * 100）。

    回傳總寫入筆數。
    """
    if df.empty or "stock_id" not in df.columns:
        return 0

    total = 0
    for sid, grp in df.groupby("stock_id", sort=False):
        sid = str(sid).strip()
        if not sid:
            continue

        grp = grp.copy()
        total_unit = pd.to_numeric(grp["unit"], errors="coerce").fillna(0).sum()
        if total_unit > 0:
            grp["percent"] = (
                pd.to_numeric(grp["unit"], errors="coerce").fillna(0) / total_unit * 100
            ).round(4)
        else:
            grp["percent"] = 0.0

        records = grp[["date", "level", "people", "unit", "percent"]].to_dict("records")
        total += upsert_tdcc_week(sid, records)

    return total


# ══════════════════════════════════════════════════════════
# tdcc_history 讀取
# ══════════════════════════════════════════════════════════

def get_tdcc_history(stock_id: str, days: int = 365) -> pd.DataFrame:
    """
    讀取個股集保歷史，回傳 DataFrame。
    格式與 get_tdcc_shareholding 回傳相同，可直接餵給 calc_holder_analysis。

    欄位：stock_id, date(datetime), level, people, unit, percent
    依 (date, level) 升冪排序。
    """
    sid = str(stock_id).strip().upper()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    conn = _get_conn()
    rows = conn.execute(
        """SELECT stock_id, date, level, people, unit, percent
           FROM tdcc_history
           WHERE stock_id = ? AND date >= ?
           ORDER BY date ASC, level ASC""",
        (sid, cutoff),
    ).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["stock_id"] = sid
    return df


def get_latest_tdcc_date(stock_id: str) -> str | None:
    """
    回傳個股在 DB 中最新的集保日期（'YYYY-MM-DD'），
    若無資料則回傳 None。
    """
    sid = str(stock_id).strip().upper()
    conn = _get_conn()
    row = conn.execute(
        "SELECT MAX(date) FROM tdcc_history WHERE stock_id = ?", (sid,)
    ).fetchone()
    return row[0] if row and row[0] else None


def count_tdcc_weeks(stock_id: str) -> int:
    """回傳個股在 DB 中有幾週資料（幾個不同日期）。"""
    sid = str(stock_id).strip().upper()
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(DISTINCT date) FROM tdcc_history WHERE stock_id = ?", (sid,)
    ).fetchone()
    return row[0] if row else 0


# ══════════════════════════════════════════════════════════
# tdcc_watchlist
# ══════════════════════════════════════════════════════════

def upsert_watchlist(stock_id: str, user_id: str = "admin",
                     last_updated: str | None = None) -> None:
    """新增或更新 watchlist 紀錄。若 last_updated 為 None，自動用今日日期。"""
    sid   = str(stock_id).strip().upper()
    today = datetime.now().strftime("%Y-%m-%d")
    lu    = last_updated or today

    with _tx() as conn:
        conn.execute(
            """INSERT INTO tdcc_watchlist (user_id, stock_id, last_updated, first_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, stock_id) DO UPDATE SET last_updated = excluded.last_updated""",
            (user_id, sid, lu, today),
        )


def get_watchlist(user_id: str = "admin") -> list[dict]:
    """回傳指定用戶的 watchlist 股票。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT stock_id, last_updated, first_seen FROM tdcc_watchlist "
        "WHERE user_id=? ORDER BY stock_id",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_stale_watchlist(user_id: str = "admin", stale_days: int = 6) -> list[str]:
    """回傳 last_updated 超過 stale_days 天（或從未更新）的股票代號清單。"""
    cutoff = (datetime.now() - timedelta(days=stale_days)).strftime("%Y-%m-%d")
    conn   = _get_conn()
    rows   = conn.execute(
        """SELECT stock_id FROM tdcc_watchlist
           WHERE user_id=? AND (last_updated IS NULL OR last_updated < ?)
           ORDER BY last_updated ASC NULLS FIRST""",
        (user_id, cutoff),
    ).fetchall()
    return [r[0] for r in rows]


# ══════════════════════════════════════════════════════════
# 維護工具
# ══════════════════════════════════════════════════════════

def get_latest_tdcc_date_all() -> str | None:
    """
    回傳 DB 中所有股票的最新集保日期（全市場最大值）。
    背景 thread 用此判斷是否需要重新下載全市場。
    """
    conn = _get_conn()
    row  = conn.execute("SELECT MAX(date) FROM tdcc_history").fetchone()
    return row[0] if row and row[0] else None


def purge_old_history(keep_days: int = 365) -> int:
    """刪除超過 keep_days 天的舊集保資料，回傳刪除筆數。"""
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    with _tx() as conn:
        cur = conn.execute(
            "DELETE FROM tdcc_history WHERE date < ?", (cutoff,)
        )
    return cur.rowcount


def get_db_stats() -> dict:
    """回傳 DB 統計資訊，供 sidebar 顯示。"""
    conn = _get_conn()
    total_rows = conn.execute(
        "SELECT COUNT(*) FROM tdcc_history"
    ).fetchone()[0]
    total_stocks = conn.execute(
        "SELECT COUNT(DISTINCT stock_id) FROM tdcc_history"
    ).fetchone()[0]
    total_weeks = conn.execute(
        "SELECT COUNT(DISTINCT date) FROM tdcc_history"
    ).fetchone()[0]
    latest = conn.execute(
        "SELECT MAX(date) FROM tdcc_history"
    ).fetchone()[0]

    return {
        "total_rows":    total_rows,
        "total_stocks":  total_stocks,
        "total_weeks":   total_weeks,
        "latest_date":   latest,
        "db_size_kb":    round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0,
    }
