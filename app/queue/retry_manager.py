"""Retry manager — backoff [5, 15, 45] min + dead-letter queue.

Współpracuje z ``state_machine.handle_running_job_result`` — nie duplikuje
logiki, tylko udostępnia helpers dla worker'a.
"""
from __future__ import annotations

import logging
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import LOGS_DIR
from ..data import shared_db
from ..data.shared_db import get_connection
from .state_machine import (
    MAX_RETRIES,
    RETRY_BACKOFF_MINUTES,
    JobStatus,
    increment_retries,
    reschedule_job,
    transition_job,
)

__all__ = [
    "should_retry",
    "next_backoff_delay",
    "schedule_retry",
    "record_dead_letter",
    "DEAD_LETTER_LOG",
]

_LOG = logging.getLogger("marketia.queue.retry_manager")

#: Dead-letter log path (append-only, JSON lines).
DEAD_LETTER_LOG: Path = LOGS_DIR / "dead_letter.log"


def _job_retries(job: Any) -> int:
    """Wyciąga retries z Row/dict/atrybutu — defensive."""
    if job is None:
        return 0
    if isinstance(job, dict):
        return int(job.get("retries", 0))
    try:
        return int(job["retries"])
    except (KeyError, TypeError, IndexError):
        pass
    return int(getattr(job, "retries", 0) or 0)


def should_retry(job: Any) -> bool:
    """True jeśli retries < MAX_RETRIES (3)."""
    return _job_retries(job) < MAX_RETRIES


def next_backoff_delay(retries: int) -> int:
    """Zwraca opóźnienie w minutach dla następnej próby.

    retries=0 → 5, retries=1 → 15, retries=2 → 45.
    Clampowane do ostatniej wartości gdy retries >= len(RETRY_BACKOFF_MINUTES).
    """
    if retries < 0:
        return RETRY_BACKOFF_MINUTES[0]
    idx = min(retries, len(RETRY_BACKOFF_MINUTES) - 1)
    return RETRY_BACKOFF_MINUTES[idx]


def schedule_retry(job_id: int, error: str = "") -> datetime:
    """Zwiększa retries, ustawia scheduled_at, RUNNING → PENDING.

    Returns:
        nowa scheduled_at (UTC).
    """
    retries = shared_db.get_pending_jobs  # noop reference — keep import used
    del retries
    current_retries = 0
    with get_connection(read_only=True) as conn:
        row = conn.execute(
            "SELECT retries, status FROM olx_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if row:
        current_retries = int(row["retries"] or 0)

    increment_retries(job_id)
    delay = next_backoff_delay(current_retries)
    new_dt = reschedule_job(job_id, delay_minutes=delay)
    try:
        transition_job(
            job_id,
            JobStatus.RUNNING,
            JobStatus.PENDING,
            reason=error or "transient_fail",
        )
    except Exception:
        # Job może być w innym stanie (np. już PAUSED przez ban_detector).
        traceback.print_exc(file=sys.stdout)
        _LOG.warning("schedule_retry: transition failed for job %d", job_id)
    return new_dt


def record_dead_letter(job_id: int, error: str) -> None:
    """Zapisuje wpis do dead-letter log (append JSON line + transition RUNNING→FAILED).

    Wymuszamy istnienie katalogu (LOGS_DIR nie musi istnieć w testach).
    """
    try:
        DEAD_LETTER_LOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    payload = {
        "job_id": job_id,
        "error": error,
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }
    try:
        import json

        with open(DEAD_LETTER_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        traceback.print_exc(file=sys.stdout)
        _LOG.warning("dead_letter write failed for job %d", job_id)

    try:
        transition_job(
            job_id,
            JobStatus.RUNNING,
            JobStatus.FAILED,
            reason=f"dead_letter:{error}",
        )
    except Exception:
        traceback.print_exc(file=sys.stdout)
        _LOG.warning("record_dead_letter: transition failed for job %d", job_id)
