"""Unit testy dla app/queue/state_machine.py — enum + transitions + DB helpers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.queue.state_machine import (
    MAX_RETRIES,
    RETRY_BACKOFF_MINUTES,
    VALID_TRANSITIONS,
    JobStatus,
    JobTransitionError,
    _as_status,
    cascade_pause_pending_jobs,
    count_by_status,
    get_job,
    get_job_retries,
    get_jobs_by_account_and_status,
    get_next_pending_job,
    increment_retries,
    reschedule_job,
    transition_job,
)


def _insert_job(db_path, sku="SKU-1", account="acc1", city="Warszawa",
                status="pending", scheduled_at=None, retries=0):
    """Helper: wstawia joba do olx_jobs i zwraca id."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    scheduled = scheduled_at or datetime.now(UTC)
    cur = conn.execute(
        "INSERT INTO olx_jobs(sku, account_name, city, scheduled_at, status, retries) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sku, account, city, scheduled, status, retries),
    )
    conn.commit()
    job_id = cur.lastrowid
    conn.close()
    return job_id


class TestConstants:
    def test_max_retries(self):
        assert MAX_RETRIES == 3

    def test_backoff_shape(self):
        assert RETRY_BACKOFF_MINUTES == (5, 15, 45)

    def test_all_statuses_have_transitions_defined(self):
        for status in JobStatus:
            assert status in VALID_TRANSITIONS

    def test_terminal_states_no_outgoing(self):
        assert VALID_TRANSITIONS[JobStatus.DONE] == set()
        assert VALID_TRANSITIONS[JobStatus.CANCELED] == set()


class TestAsStatus:
    def test_from_enum(self):
        assert _as_status(JobStatus.PENDING) is JobStatus.PENDING

    def test_from_string(self):
        assert _as_status("running") is JobStatus.RUNNING

    def test_unknown_string_raises(self):
        with pytest.raises(JobTransitionError, match="Nieznany status"):
            _as_status("nonexistent")

    def test_unknown_type_raises(self):
        with pytest.raises(JobTransitionError, match="Nieznany typ"):
            _as_status(42)  # type: ignore[arg-type]


class TestTransition:
    def test_valid_pending_to_running(self, temp_db):
        job_id = _insert_job(temp_db, status="pending")
        transition_job(job_id, "pending", "running")
        assert get_job(job_id)["status"] == "running"

    def test_valid_running_to_done(self, temp_db):
        job_id = _insert_job(temp_db, status="running")
        transition_job(job_id, "running", "done")
        assert get_job(job_id)["status"] == "done"

    def test_invalid_done_to_pending_raises(self, temp_db):
        job_id = _insert_job(temp_db, status="done")
        with pytest.raises(JobTransitionError, match="Invalid transition done -> pending"):
            transition_job(job_id, "done", "pending")

    def test_invalid_canceled_to_running_raises(self, temp_db):
        job_id = _insert_job(temp_db, status="canceled")
        with pytest.raises(JobTransitionError):
            transition_job(job_id, "canceled", "running")

    def test_reason_stored_as_last_error(self, temp_db):
        job_id = _insert_job(temp_db, status="running")
        transition_job(job_id, "running", "failed", reason="network")
        assert get_job(job_id)["last_error"] == "network"


class TestRetriesAndReschedule:
    def test_get_retries_zero(self, temp_db):
        job_id = _insert_job(temp_db)
        assert get_job_retries(job_id) == 0

    def test_increment_retries(self, temp_db):
        job_id = _insert_job(temp_db)
        increment_retries(job_id)
        increment_retries(job_id)
        assert get_job_retries(job_id) == 2

    def test_reschedule_returns_future_datetime(self, temp_db):
        job_id = _insert_job(temp_db)
        before = datetime.now(UTC)
        new_dt = reschedule_job(job_id, delay_minutes=15)
        assert new_dt > before + timedelta(minutes=14)
        assert new_dt < before + timedelta(minutes=16)

    def test_missing_job_returns_zero_retries(self, temp_db):
        assert get_job_retries(99999) == 0


class TestQueries:
    def test_count_by_status_empty(self, temp_db):
        assert count_by_status() == {}

    def test_count_by_status_mixed(self, temp_db):
        _insert_job(temp_db, status="pending")
        _insert_job(temp_db, status="pending")
        _insert_job(temp_db, status="done")
        assert count_by_status() == {"pending": 2, "done": 1}

    def test_get_jobs_by_account_and_status(self, temp_db):
        _insert_job(temp_db, account="a1", status="pending")
        _insert_job(temp_db, account="a1", status="pending")
        _insert_job(temp_db, account="a2", status="pending")
        rows = get_jobs_by_account_and_status("a1", JobStatus.PENDING)
        assert len(rows) == 2

    def test_get_next_pending_returns_earliest(self, temp_db):
        past = datetime.now(UTC) - timedelta(hours=1)
        future = datetime.now(UTC) + timedelta(hours=1)
        _insert_job(temp_db, account="a1", status="pending", scheduled_at=future)
        j2 = _insert_job(temp_db, account="a1", status="pending", scheduled_at=past)
        row = get_next_pending_job("a1")
        assert row is not None
        assert row["id"] == j2

    def test_get_next_pending_none_when_all_future(self, temp_db):
        future = datetime.now(UTC) + timedelta(hours=1)
        _insert_job(temp_db, account="a1", status="pending", scheduled_at=future)
        assert get_next_pending_job("a1") is None


class TestCascadePause:
    def test_empty_accounts_noop(self, temp_db):
        assert cascade_pause_pending_jobs([], datetime.now(UTC)) == 0

    def test_pauses_pending_across_accounts(self, temp_db):
        _insert_job(temp_db, account="a1", status="pending")
        _insert_job(temp_db, account="a1", status="pending")
        _insert_job(temp_db, account="a2", status="pending")
        _insert_job(temp_db, account="a2", status="running")  # NIE pending → nie pauza
        until = datetime.now(UTC) + timedelta(hours=1)
        n = cascade_pause_pending_jobs(["a1", "a2"], until, reason="ban_test")
        assert n == 3
        # a1 + a2 pending → paused; a2 running → nadal running
        assert count_by_status().get("paused") == 3
        assert count_by_status().get("running") == 1
