"""Shared SQLite DB — współdzielony z Marketia XML Pro.

Umowa: OLX Poster czyta tabelę ``products`` (own by XML Pro) tylko-do-odczytu
oraz zarządza własnymi tabelami z prefiksem ``olx_*`` + ``variant_cache`` +
``schema_migrations``.

WAL mode aktywny — bezpieczne równoległe czytanie/pisanie z drugiego procesu.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from ..config import DB_PATH, PROMPT_VERSION
from .schema import MIGRATIONS

__all__ = [
    "DB_PATH",
    "get_connection",
    "run_migrations",
    "save_listing",
    "get_pending_jobs",
    "mark_job_status",
    "get_or_create_account_meta",
    "set_account_pause",
    "update_last_health_check",
    "variant_cache_get",
    "variant_cache_save",
    "load_from_shared_db",
]


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection(read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Kontekstowe połączenie do shared DB (WAL, foreign_keys, Row factory).

    Auto-close + commit on exit (rollback jeśli exception).
    """
    _ensure_parent(DB_PATH)
    conn = sqlite3.connect(
        str(DB_PATH),
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        timeout=15.0,
    )
    conn.row_factory = sqlite3.Row
    try:
        # WAL raz na proces jest OK — powtórne PRAGMA nie szkodzi.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=15000;")
        yield conn
        if not read_only:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations() -> list[int]:
    """Aplikuje pending migracje w kolejności. Zwraca listę zaaplikowanych wersji."""
    applied: list[int] = []
    with get_connection() as conn:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY,"
            " applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);"
        )
        existing = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for version, sql in MIGRATIONS:
            if version in existing:
                continue
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (version,),
            )
            applied.append(version)
    return applied


# --- olx_listings ---------------------------------------------------------

def save_listing(
    sku: str,
    account_name: str,
    city: str,
    url: str | None,
    screenshot_path: str | None,
    status: str = "active",
) -> int:
    """Streaming save po każdej pojedynczej publikacji (nie po batchu).

    Zwraca ``lastrowid``.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO olx_listings(sku, account_name, city, url, screenshot_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sku, account_name, city, url, screenshot_path, status),
        )
        return int(cur.lastrowid)


# --- olx_jobs -------------------------------------------------------------

def get_pending_jobs(limit: int = 100) -> list[sqlite3.Row]:
    """Zwraca jobs w statusie 'pending', sortowane po scheduled_at."""
    with get_connection(read_only=True) as conn:
        return conn.execute(
            """
            SELECT * FROM olx_jobs
            WHERE status = 'pending'
            ORDER BY COALESCE(scheduled_at, created_at) ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def mark_job_status(
    job_id: int,
    status: str,
    last_error: str | None = None,
    increment_retries: bool = False,
) -> None:
    """Streaming: commit natychmiast po zmianie statusu joba."""
    with get_connection() as conn:
        if increment_retries:
            conn.execute(
                """
                UPDATE olx_jobs
                SET status = ?, last_error = ?, retries = retries + 1
                WHERE id = ?
                """,
                (status, last_error, job_id),
            )
        else:
            conn.execute(
                "UPDATE olx_jobs SET status = ?, last_error = ? WHERE id = ?",
                (status, last_error, job_id),
            )


# --- olx_accounts_meta ----------------------------------------------------

def get_or_create_account_meta(
    name: str,
    warmup_days: int = 0,
) -> sqlite3.Row:
    """Idempotentne. Nie modyfikuje istniejącego rekordu."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO olx_accounts_meta(name, warmup_days_remaining)
            VALUES (?, ?)
            """,
            (name, warmup_days),
        )
        row = conn.execute(
            "SELECT * FROM olx_accounts_meta WHERE name = ?", (name,)
        ).fetchone()
    return row  # type: ignore[return-value]


def set_account_pause(
    name: str,
    is_paused: bool,
    reason: str | None = None,
) -> None:
    """Ustawia flagę pauzy dla konta. Streaming save.

    Args:
        name: nazwa konta.
        is_paused: True = pauza, False = aktywne.
        reason: dowolny tekst (max ~200 chars, wyświetlane w GUI).
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE olx_accounts_meta
            SET is_paused = ?, pause_reason = ?
            WHERE name = ?
            """,
            (1 if is_paused else 0, reason, name),
        )


def update_last_health_check(name: str, ts: datetime | None = None) -> None:
    """Aktualizuje timestamp ostatniego health check-u (idempotent)."""
    ts = ts or datetime.now(UTC)
    with get_connection() as conn:
        conn.execute(
            "UPDATE olx_accounts_meta SET last_health_check = ? WHERE name = ?",
            (ts, name),
        )


# --- variant_cache --------------------------------------------------------

def variant_cache_get(
    cache_hash: str,
    prompt_version: str = PROMPT_VERSION,
) -> dict[str, Any] | None:
    """Zwraca cached wariant TYLKO jeśli prompt_version zgadza się z bieżącym.

    Cache versioning enforced NA ODCZYCIE — stary wpis nie zwraca danych, ale
    pozostaje w tabeli (usuwany osobnym GC). Dzięki temu bump PROMPT_VERSION
    automatycznie unieważnia cały cache.
    """
    with get_connection(read_only=True) as conn:
        row = conn.execute(
            "SELECT variant_json, prompt_version FROM variant_cache WHERE hash = ?",
            (cache_hash,),
        ).fetchone()
    if row is None:
        return None
    if row["prompt_version"] != prompt_version:
        return None  # stale — force regenerate
    try:
        return json.loads(row["variant_json"])
    except json.JSONDecodeError:
        return None


def variant_cache_save(
    cache_hash: str,
    sku: str,
    city: str,
    variant: dict[str, Any],
    prompt_version: str = PROMPT_VERSION,
) -> None:
    """Upsert wariantu — bump'uje created_at przy nadpisaniu."""
    payload = json.dumps(variant, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO variant_cache(hash, sku, city, prompt_version, variant_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(hash) DO UPDATE SET
                sku            = excluded.sku,
                city           = excluded.city,
                prompt_version = excluded.prompt_version,
                variant_json   = excluded.variant_json,
                created_at     = excluded.created_at
            """,
            (cache_hash, sku, city, prompt_version, payload, datetime.now(UTC)),
        )


# --- read-only produkty (własność Marketia XML Pro) -----------------------

def load_from_shared_db(limit: int | None = None) -> list[dict[str, Any]]:
    """SELECT z tabeli ``products`` — TYLKO DO ODCZYTU.

    Jeśli tabela nie istnieje (np. XML Pro jeszcze nie zainicjalizował DB) →
    zwraca pustą listę zamiast rzucać. GUI powinno pokazać podpowiedź.
    """
    with get_connection(read_only=True) as conn:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
        ).fetchone()
        if not exists:
            return []
        sql = "SELECT * FROM products"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
