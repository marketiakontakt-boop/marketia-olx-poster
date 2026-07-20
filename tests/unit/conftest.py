"""Fixtures dla unit tests — izolowana SQLite tempdb + mock keyring."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Świeża tempdb + migracje. Patchuje DB_PATH we wszystkich modułach które
    ją importują z app.config oraz z app.data.shared_db (re-export)."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db_path)
    monkeypatch.setattr("app.data.shared_db.DB_PATH", db_path)

    from app.data import shared_db
    shared_db.run_migrations()
    return db_path


@pytest.fixture
def mock_keyring(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Zastępuje `keyring` in-memory dictem."""
    store: dict[tuple[str, str], str] = {}

    def _get(service: str, username: str) -> str | None:
        return store.get((service, username))

    def _set(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def _delete(service: str, username: str) -> None:
        store.pop((service, username), None)

    monkeypatch.setattr("app.security.vault.keyring.get_password", _get)
    monkeypatch.setattr("app.security.vault.keyring.set_password", _set)
    monkeypatch.setattr("app.security.vault.keyring.delete_password", _delete)
    return store
