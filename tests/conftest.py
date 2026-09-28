import pytest

import database


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Point database.py at a throwaway sqlite file so tests never touch data/trades.db."""
    db_file = tmp_path / "test_trades.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return database
