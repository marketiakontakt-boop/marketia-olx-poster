"""Job state machine — 7 stanów z walidowanymi transycjami.

SPEC sekcja 8. State diagram: patrz ``_meta/marketia-olx-poster/state_machine_draft.md``.

Streaming save: każdy ``transition_job`` natychmiast persist do ``olx_jobs``.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from ..data import shared_db
from ..data.shared_db import get_connection

__all__ = [
    "JobStatus",
    "JobTransitionError",
    "VALID_TRANSITIONS",
    "transition_job",
    "handle_running_job_result",
    "count_by_status",
    "get_jobs_by_account_and_status",
    "get_next_pending_job",
    "cascade_pause_pending_jobs",
    "get_job",
    "get_job_retries",
    "increment_retries",
    "reschedule_job",
    "RETRY_BACKOFF_MINUTES",
    "MAX_RETRIES",
]

_LOG = logging.getLogger("marketia.queue.state_machine")

#: Backoff w minutach: retry 0→5min, retry 1→15min, retry 2→45min.
RETRY_BACKOFF_MINUTES: tuple[int, ...] = (5, 15, 45)
MAX_RETRIES: int = 3


class JobStatus(str, Enum):
    """7 stanów joba."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELED = "canceled"
    SCHEDULED_LATER = "scheduled_later"


VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.PENDING: {
        JobStatus.RUNNING,
        JobStatus.SCHEDULED_LATER,
        JobStatus.PAUSED,
        JobStatus.CANCELED,
    },
    JobStatus.RUNNING: {
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.PENDING,
        JobStatus.PAUSED,
    },
    JobStatus.SCHEDULED_LATER: {
        JobStatus.PENDING,
        JobStatus.CANCELED,
    },
    JobStatus.PAUSED: {
        JobStatus.PENDING,
        JobStatus.CANCELED,
    },
    JobStatus.FAILED: {
        JobStatus.PENDING,
        JobStatus.CANCELED,
    },
    JobStatus.DONE: set(),
    JobStatus.CANCELED: set(),
}


class JobTransitionError(RuntimeError):
    """Rzucane gdy transition z from→to nie jest w VALID_TRANSITIONS."""


# --- Helpers --------------------------------------------------------------

def _as_status(value: Any) -> JobStatus:
    """Konwertuje str/JobStatus → JobStatus (defensive)."""
    if isinstance(value, JobStatus):
        return value
    if isinstance(value, str):
        try:
            return JobStatus(value)
        except ValueError as exc:
            raise JobTransitionError(f"Nieznany status: {value!r}") from exc
    raise JobTransitionError(f"Nieznany typ statusu: {type(value).__name__}")


# --- Core transition ------------------------------------------------------

def transition_job(
    job_id: int,
    from_state: JobStatus | str,
    to_state: JobStatus | str,
    reason: str = "",
) -> None:
    """Bezpieczna zmiana stanu z walidacją. Streaming save do olx_jobs.

    Raises:
        JobTransitionError: gdy transition niedozwolony.
    """
    fs = _as_status(from_state)
    ts = _as_status(to_state)
    allowed = VALID_TRANSITIONS.get(fs, set())
    if ts not in allowed:
        raise JobTransitionError(
            f"Invalid transition {fs.value} -> {ts.value} for job {job_id}"
        )
    shared_db.mark_job_status(job_id, ts.value, last_error=reason or None)
    _LOG.debug("job %d transition %s -> %s (%s)", job_id, fs.value, ts.value, reason)


# --- Job lookup helpers ---------------------------------------------------

def get_job(job_id: int) -> sqlite3.Row | None:
    with get_connection(read_only=True) as conn:
        return conn.execute(
            "SELECT * FROM olx_jobs WHERE id = ?", (job_id,)
        ).fetchone()


def get_job_retries(job_id: int) -> int:
    row = get_job(job_id)
    return int(row["retries"]) if row else 0


def increment_retries(job_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE olx_jobs SET retries = retries + 1 WHERE id = ?", (job_id,)
        )


def reschedule_job(job_id: int, delay_minutes: int) -> datetime:
    """Ustawia ``scheduled_at`` = now + delay. Zwraca nową datetime."""
    new_dt = datetime.now(UTC) + timedelta(minutes=delay_minutes)
    with get_connection() as conn:
        conn.execute(
            "UPDATE olx_jobs SET scheduled_at = ? WHERE id = ?", (new_dt, job_id)
        )
    return new_dt


# --- Retry integration ----------------------------------------------------

async def handle_running_job_result(
    job_id: int,
    success: bool,
    error: str | None = None,
    ban_reason: str | None = None,
) -> None:
    """Wołane po każdej próbie wystawienia z running workera.

    Transitions:
        - success → RUNNING → DONE
        - ban_reason set → RUNNING → PAUSED (cascade handled by ban_detector)
        - transient fail, retries < MAX_RETRIES → RUNNING → PENDING + reschedule
        - retries >= MAX_RETRIES → RUNNING → FAILED (dead-letter przez retry_manager)
    """
    if success:
        transition_job(job_id, JobStatus.RUNNING, JobStatus.DONE)
        return

    if ban_reason:
        transition_job(
            job_id,
            JobStatus.RUNNING,
            JobStatus.PAUSED,
            reason=f"ban:{ban_reason}",
        )
        return

    retries = get_job_retries(job_id)
    if retries < MAX_RETRIES:
        increment_retries(job_id)
        backoff = RETRY_BACKOFF_MINUTES[min(retries, len(RETRY_BACKOFF_MINUTES) - 1)]
        reschedule_job(job_id, delay_minutes=backoff)
        transition_job(
            job_id,
            JobStatus.RUNNING,
            JobStatus.PENDING,
            reason=error or "transient_fail",
        )
    else:
        transition_job(
            job_id,
            JobStatus.RUNNING,
            JobStatus.FAILED,
            reason=error or "max_retries_exhausted",
        )


# --- Query helpers (GUI tab Kolejka) --------------------------------------

def count_by_status() -> dict[str, int]:
    """Agregat per status. Używane w GUI header oraz w statusbarze."""
    with get_connection(read_only=True) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM olx_jobs GROUP BY status"
        ).fetchall()
    return {row["status"]: int(row["cnt"]) for row in rows}


def get_jobs_by_account_and_status(
    account: str,
    status: JobStatus | str,
    limit: int = 100,
) -> list[sqlite3.Row]:
    st = _as_status(status)
    with get_connection(read_only=True) as conn:
        return conn.execute(
            """
            SELECT * FROM olx_jobs
            WHERE account_name = ? AND status = ?
            ORDER BY COALESCE(scheduled_at, created_at) ASC
            LIMIT ?
            """,
            (account, st.value, limit),
        ).fetchall()


def get_next_pending_job(account: str, now: datetime | None = None) -> sqlite3.Row | None:
    """Worker per-account: bierze najbliższy pending w slocie."""
    ts = now or datetime.now(UTC)
    with get_connection(read_only=True) as conn:
        return conn.execute(
            """
            SELECT * FROM olx_jobs
            WHERE account_name = ? AND status = ? AND scheduled_at <= ?
            ORDER BY scheduled_at ASC
            LIMIT 1
            """,
            (account, JobStatus.PENDING.value, ts),
        ).fetchone()


# --- Cascade pause hook (Faza 4 ban_detector) -----------------------------

def cascade_pause_pending_jobs(
    cascade_accounts: list[str],
    until: datetime,
    reason: str = "cascade_pause",
) -> int:
    """Pauzuje wszystkie PENDING jobs na innych kontach do ``until``.

    Zwraca liczbę zpauzowanych jobs.

    Uwaga: to jest hook dla ``ban_detector.trigger_ban_action``. Wywołanie
    tego z pustej listy jest no-op.
    """
    if not cascade_accounts:
        return 0
    total = 0
    with get_connection() as conn:
        for account in cascade_accounts:
            cur = conn.execute(
                """
                UPDATE olx_jobs
                SET status = ?, last_error = ?, scheduled_at = ?
                WHERE account_name = ? AND status = ?
                """,
                (
                    JobStatus.PAUSED.value,
                    reason,
                    until,
                    account,
                    JobStatus.PENDING.value,
                ),
            )
            total += cur.rowcount or 0
    _LOG.info(
        "cascade_pause: %d jobs paused across %d accounts until %s",
        total,
        len(cascade_accounts),
        until.isoformat(),
    )
    return total
