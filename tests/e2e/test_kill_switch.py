"""Kill switch lifecycle — activate → cancel jobs + pause accounts → deactivate.

Nie wymaga live OLX. Manipuluje DB bezpośrednio + testuje globalną flagę.
"""
from __future__ import annotations

import pytest

from app.data.shared_db import get_connection
from app.monitor.kill_switch import (
    is_kill_switch_active,
    kill_switch_activate,
    kill_switch_deactivate,
)
from app.queue.state_machine import JobStatus


def _seed_jobs_and_accounts(conn) -> None:
    """5 pending jobs + 3 konta w meta."""
    for i in range(5):
        conn.execute(
            "INSERT INTO olx_jobs(sku, account_name, city, status) "
            "VALUES (?, ?, ?, ?)",
            (f"SKU{i}", "test-account", "Warszawa", JobStatus.PENDING.value),
        )
    for name in ("a", "b", "c"):
        conn.execute(
            "INSERT INTO olx_accounts_meta(name) VALUES (?)",
            (name,),
        )


def test_kill_switch_lifecycle(clean_db):
    """Full lifecycle: activate → jobs canceled + accounts paused → deactivate."""
    # Reset stanu globalnego (poprzedni test mógł zostawić True).
    if is_kill_switch_active():
        kill_switch_deactivate(user_confirmed=True)

    with get_connection() as conn:
        _seed_jobs_and_accounts(conn)

    assert not is_kill_switch_active()

    result = kill_switch_activate(reason="test")

    assert is_kill_switch_active()
    assert result["canceled_jobs"] == 5
    assert result["paused_accounts"] == 3

    with get_connection() as conn:
        rows = conn.execute("SELECT status FROM olx_jobs").fetchall()
    assert rows, "brak wierszy w olx_jobs — seed failed?"
    assert all(r["status"] == JobStatus.CANCELED.value for r in rows)

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT is_paused FROM olx_accounts_meta"
        ).fetchall()
    assert all(r["is_paused"] == 1 for r in rows)

    # Deactivate wymaga confirmed=True.
    with pytest.raises(RuntimeError):
        kill_switch_deactivate()

    kill_switch_deactivate(user_confirmed=True)
    assert not is_kill_switch_active()

    # BUT: accounts still paused — user musi ręcznie odblokować.
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT is_paused FROM olx_accounts_meta"
        ).fetchall()
    assert all(r["is_paused"] == 1 for r in rows), (
        "kill_switch_deactivate NIE POWINIEN odblokowywać kont"
    )


def test_kill_switch_no_pending_jobs(clean_db):
    """Aktywacja przy pustym stanie — 0 canceled + 0 paused, ale flag=True."""
    if is_kill_switch_active():
        kill_switch_deactivate(user_confirmed=True)

    assert not is_kill_switch_active()
    result = kill_switch_activate(reason="empty_state_test")

    assert is_kill_switch_active()
    assert result["canceled_jobs"] == 0
    assert result["paused_accounts"] == 0

    kill_switch_deactivate(user_confirmed=True)
    assert not is_kill_switch_active()
