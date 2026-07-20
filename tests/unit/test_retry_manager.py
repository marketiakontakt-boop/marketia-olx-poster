"""Unit testy dla app/queue/retry_manager.py — backoff + dead-letter."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.queue import retry_manager
from app.queue.retry_manager import (
    next_backoff_delay,
    record_dead_letter,
    schedule_retry,
    should_retry,
)
from app.queue.state_machine import RETRY_BACKOFF_MINUTES


def _insert_job(db_path, status="running", retries=0):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    scheduled = datetime.now(UTC)
    cur = conn.execute(
        "INSERT INTO olx_jobs(sku, account_name, city, scheduled_at, status, retries) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("SKU-1", "acc1", "Warszawa", scheduled, status, retries),
    )
    conn.commit()
    job_id = cur.lastrowid
    conn.close()
    return job_id


class TestShouldRetry:
    def test_below_max_true(self):
        assert should_retry({"retries": 0}) is True
        assert should_retry({"retries": 2}) is True

    def test_at_max_false(self):
        assert should_retry({"retries": 3}) is False

    def test_above_max_false(self):
        assert should_retry({"retries": 10}) is False

    def test_none_job_returns_true(self):
        # None → treated as retries=0 → True
        assert should_retry(None) is True

    def test_dict_missing_retries_key(self):
        assert should_retry({}) is True


class TestNextBackoffDelay:
    def test_retry_zero(self):
        assert next_backoff_delay(0) == RETRY_BACKOFF_MINUTES[0]  # 5

    def test_retry_one(self):
        assert next_backoff_delay(1) == RETRY_BACKOFF_MINUTES[1]  # 15

    def test_retry_two(self):
        assert next_backoff_delay(2) == RETRY_BACKOFF_MINUTES[2]  # 45

    def test_clamped_to_last(self):
        # retries=99 → clamp na ostatni index
        assert next_backoff_delay(99) == RETRY_BACKOFF_MINUTES[-1]

    def test_negative_returns_first(self):
        assert next_backoff_delay(-1) == RETRY_BACKOFF_MINUTES[0]


class TestScheduleRetry:
    def test_increments_retries_and_returns_future(self, temp_db):
        job_id = _insert_job(temp_db, status="running", retries=0)
        before = datetime.now(UTC)
        new_dt = schedule_retry(job_id, error="test_fail")
        # retries=0 → backoff 5 min
        assert new_dt > before + timedelta(minutes=4)
        assert new_dt < before + timedelta(minutes=6)

        # Sprawdź w DB
        from app.queue.state_machine import get_job, get_job_retries
        assert get_job_retries(job_id) == 1
        assert get_job(job_id)["status"] == "pending"

    def test_uses_correct_backoff_after_first_retry(self, temp_db):
        job_id = _insert_job(temp_db, status="running", retries=1)
        before = datetime.now(UTC)
        new_dt = schedule_retry(job_id)
        # retries=1 → backoff 15 min
        assert new_dt > before + timedelta(minutes=14)
        assert new_dt < before + timedelta(minutes=16)


class TestDeadLetter:
    def test_writes_json_line(self, temp_db, tmp_path: Path, monkeypatch):
        dl_path = tmp_path / "dead_letter.log"
        monkeypatch.setattr(retry_manager, "DEAD_LETTER_LOG", dl_path)
        job_id = _insert_job(temp_db, status="running")

        record_dead_letter(job_id, "permanent_failure")

        assert dl_path.exists()
        content = dl_path.read_text(encoding="utf-8").strip()
        payload = json.loads(content)
        assert payload["job_id"] == job_id
        assert payload["error"] == "permanent_failure"
        assert "timestamp" in payload

    def test_transitions_running_to_failed(self, temp_db, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(retry_manager, "DEAD_LETTER_LOG", tmp_path / "dl.log")
        job_id = _insert_job(temp_db, status="running")

        record_dead_letter(job_id, "err")

        from app.queue.state_machine import get_job
        assert get_job(job_id)["status"] == "failed"

    def test_appends_multiple_entries(self, temp_db, tmp_path: Path, monkeypatch):
        dl_path = tmp_path / "dl.log"
        monkeypatch.setattr(retry_manager, "DEAD_LETTER_LOG", dl_path)
        j1 = _insert_job(temp_db, status="running")
        j2 = _insert_job(temp_db, status="running")

        record_dead_letter(j1, "err1")
        record_dead_letter(j2, "err2")

        lines = dl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["job_id"] == j1
        assert json.loads(lines[1])["job_id"] == j2

    def test_creates_parent_dir(self, temp_db, tmp_path: Path, monkeypatch):
        # Ustaw dead-letter w nieistniejącym katalogu
        deep_path = tmp_path / "a" / "b" / "c" / "dl.log"
        monkeypatch.setattr(retry_manager, "DEAD_LETTER_LOG", deep_path)
        job_id = _insert_job(temp_db, status="running")

        record_dead_letter(job_id, "err")
        assert deep_path.exists()
