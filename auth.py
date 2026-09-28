"""
auth.py — 帳號認證模組
職責：
  - 維護 data/auth.db（users 表）
  - 提供 verify_password / create_user / list_users 等 CRUD
  - 不依賴 Streamlit，可獨立 import
"""

from __future__ import annotations
import os
import secrets
import sqlite3
import warnings
from pathlib import Path

import bcrypt

Path("data").mkdir(exist_ok=True)
DB_PATH = "data/auth.db"

# 首次啟動的 admin 密碼：優先讀環境變數，否則隨機產生（只在終端機顯示一次）
_ADMIN_PASSWORD_ENV = "WISESTOCK_ADMIN_PASSWORD"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db() -> None:
    """建立 users table（冪等）。若 table 為空，自動建立 admin 帳號。"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name  TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'user',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login    TEXT
        )
    """)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        initial_password = os.environ.get(_ADMIN_PASSWORD_ENV) or secrets.token_urlsafe(12)
        _hash = bcrypt.hashpw(initial_password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role) VALUES (?,?,?,?)",
            ("admin", "系統管理員", _hash, "admin"),
        )
        conn.commit()
        warnings.warn(
            f"\n{'='*60}\n"
            f"  首次啟動：已建立 admin 帳號，初始密碼為 '{initial_password}'\n"
            f"  請登入後立即至 Sidebar「修改密碼」更改！\n"
            f"{'='*60}",
            stacklevel=2,
        )
    conn.close()


def verify_password(username: str, password: str) -> dict | None:
    """驗證帳密，成功回傳 user dict，失敗回傳 None。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, username, display_name, password_hash, role, is_active "
        "FROM users WHERE username=? COLLATE NOCASE",
        (username.strip(),),
    ).fetchone()
    conn.close()

    if row is None:
        return None
    if not row["is_active"]:
        return None
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None

    return {
        "id":           row["id"],
        "username":     row["username"],
        "display_name": row["display_name"],
        "role":         row["role"],
    }


def update_last_login(username: str) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE username=? COLLATE NOCASE",
        (username,),
    )
    conn.commit()
    conn.close()


def create_user(username: str, display_name: str, password: str, role: str = "user") -> bool:
    """建立新帳號，username 重複時回傳 False。"""
    _hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role) VALUES (?,?,?,?)",
            (username.strip(), display_name.strip(), _hash, role),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False


def list_users() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, username, display_name, role, is_active, created_at, last_login "
        "FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user_active(username: str, is_active: bool) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET is_active=? WHERE username=? COLLATE NOCASE",
        (1 if is_active else 0, username),
    )
    conn.commit()
    conn.close()


def reset_password(username: str, new_password: str) -> None:
    _hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET password_hash=? WHERE username=? COLLATE NOCASE",
        (_hash, username),
    )
    conn.commit()
    conn.close()


def delete_user(username: str) -> None:
    conn = _get_conn()
    conn.execute(
        "DELETE FROM users WHERE username=? COLLATE NOCASE AND role != 'admin'",
        (username,),
    )
    conn.commit()
    conn.close()


def get_trade_count(username: str) -> int:
    """回傳該帳號的交易筆數（刪除前警告用）。"""
    try:
        conn = sqlite3.connect("data/trades.db")
        row = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE user_id=?", (username,)
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0
