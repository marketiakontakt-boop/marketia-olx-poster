"""Job scheduler — enqueue wariantów, pick next, worker loop.

Streaming save: każdy INSERT jobs (per wariant) + każde transition (per state)
persist do ``olx_jobs`` natychmiast (nie po batchu).

Worker loop ``run_pending_jobs_for_account`` — Faza 4 integracja z BrowserPool.
Tutaj (Faza 3) tylko szkielet + kontrakt.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
import traceback
from datetime import date, datetime
from typing import Any, Callable, Optional

from ..data import shared_db
from ..data.shared_db import get_connection
from ..olx.city_variants import VariantSpec
from .daily_planner import plan_account_daily
from .state_machine import (
    JobStatus,
    get_next_pending_job,
    handle_running_job_result,
    transition_job,
)

__all__ = [
    "enqueue_variants",
    "pick_next_job",
    "run_pending_jobs_for_account",
    "count_jobs_for_account_today",
]

_LOG = logging.getLogger("marketia.queue.job_scheduler")


# --- Enqueue --------------------------------------------------------------

def enqueue_variants(
    sku: str,
    account: str,
    variants: list[VariantSpec],
    *,
    today: Optional[date] = None,
    rng_seed: Optional[int] = None,
) -> list[int]:
    """Wpisuje warianty do ``olx_jobs`` z scheduled_at z ``plan_account_daily``.

    Streaming save: każdy INSERT commituje osobno (via WAL, timeout=15s).

    Args:
        sku: SKU produktu (nadrzędne dla wszystkich wariantów).
        account: nazwa konta.
        variants: lista wariantów per miasto.
        today: opcjonalne (do testów).
        rng_seed: opcjonalne (do testów deterministic).

    Returns:
        list[int] — nowe job.id w kolejności wpisów.
    """
    if not variants:
        return []

    schedule = plan_account_daily(
        account,
        jobs_count=len(variants),
        today=today,
        rng_seed=rng_seed,
    )
    if not schedule:
        _LOG.warning(
            "enqueue_variants: pusty schedule dla %s (jobs=%d) — konto nie ma slotu?",
            account,
            len(variants),
        )
        return []

    # Jeśli schedule krótszy niż variants — wpisujemy tyle ile mieści się w slocie.
    # Pozostałe variants pomijamy (worker w Fazie 4 może retry na następny dzień).
    job_ids: list[int] = []
    for variant, scheduled_at in zip(variants, schedule):
        try:
            job_id = _insert_job(
                sku=sku,
                account=account,
                city=variant.city,
                scheduled_at=scheduled_at,
            )
            job_ids.append(job_id)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            _LOG.warning(
                "enqueue_variants: INSERT failed sku=%s city=%s",
                sku,
                variant.city,
            )
    return job_ids


def _insert_job(
    sku: str,
    account: str,
    city: str,
    scheduled_at: datetime,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO olx_jobs(sku, account_name, city, scheduled_at, status, retries)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (sku, account, city, scheduled_at, JobStatus.PENDING.value),
        )
        return int(cur.lastrowid)


# --- Pick next ------------------------------------------------------------

def pick_next_job(account: str, now: datetime | None = None) -> sqlite3.Row | None:
    """Bierze najbliższy pending w slocie konta.

    Delegat do ``state_machine.get_next_pending_job``.
    """
    return get_next_pending_job(account, now=now)


def count_jobs_for_account_today(
    account: str,
    day: Optional[date] = None,
) -> int:
    """Ile jobs zaplanowano na dzisiaj dla konta (wszystkie statusy)."""
    day = day or date.today()
    day_start = datetime.combine(day, datetime.min.time())
    day_end = datetime.combine(day, datetime.max.time())
    with get_connection(read_only=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM olx_jobs
            WHERE account_name = ?
              AND scheduled_at BETWEEN ? AND ?
            """,
            (account, day_start, day_end),
        ).fetchone()
    return int(row["cnt"]) if row else 0


# --- Worker loop (Faza 4 integracja) --------------------------------------

async def run_pending_jobs_for_account(
    account: str,
    *,
    execute_job: Callable[[sqlite3.Row], "asyncio.Future[Any] | Any"],
    should_stop: Callable[[], bool] | None = None,
    poll_interval_s: float = 30.0,
) -> None:
    """Główna pętla worker'a per konto.

    W Fazie 3 tylko kontrakt — Faza 4 podłączy ``execute_job`` = wywołanie
    ``BrowserPool + listing_creator.create_listing``.

    Args:
        account: nazwa konta.
        execute_job: async callable(job_row) → ListingResult-like (attrs
            success, error, metadata).
        should_stop: opcjonalny predykat sprawdzany przed każdym pickem
            (dla kill switch).
        poll_interval_s: co ile s polling gdy brak pending job w slocie.
    """
    _LOG.info("worker started for account=%s", account)
    try:
        while True:
            if should_stop and should_stop():
                _LOG.info("worker stopped (should_stop=True) for %s", account)
                return

            job = pick_next_job(account)
            if job is None:
                await asyncio.sleep(poll_interval_s)
                continue

            job_id = int(job["id"])
            try:
                transition_job(job_id, JobStatus.PENDING, JobStatus.RUNNING)
            except Exception:
                traceback.print_exc(file=sys.stdout)
                _LOG.warning("worker: transition PENDING->RUNNING failed job=%d", job_id)
                await asyncio.sleep(1)
                continue

            try:
                result = execute_job(job)
                if asyncio.iscoroutine(result):
                    result = await result
                success = bool(getattr(result, "success", False))
                error = getattr(result, "error", None)
                ban_reason = None
                metadata = getattr(result, "metadata", None) or {}
                if isinstance(metadata, dict):
                    ban_reason = metadata.get("ban_reason")
                await handle_running_job_result(
                    job_id,
                    success=success,
                    error=error,
                    ban_reason=ban_reason,
                )
                if success:
                    # Streaming save już zrobiony w listing_creator; tutaj jest fallback.
                    pass
            except Exception as exc:
                traceback.print_exc(file=sys.stdout)
                _LOG.exception("worker: execute_job crashed job=%d", job_id)
                await handle_running_job_result(
                    job_id,
                    success=False,
                    error=f"crash:{exc}",
                )
    except asyncio.CancelledError:
        _LOG.info("worker cancelled for account=%s", account)
        raise
    except Exception:
        traceback.print_exc(file=sys.stdout)
        _LOG.exception("worker crashed for account=%s", account)
