import pytest

import database
import i18n


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Point database.py at a throwaway sqlite file so tests never touch data/trades.db."""
    db_file = tmp_path / "test_trades.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return database


@pytest.fixture(autouse=True)
def zh_lang(monkeypatch):
    """既有測試以中文字串斷言；需要測英文時在測試裡再 monkeypatch 成 "en"。"""
    monkeypatch.setattr(i18n, "get_lang", lambda: "zh")
