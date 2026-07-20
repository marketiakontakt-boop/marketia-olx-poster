"""SQLite schema DDL + wersje migracji.

Kontrakt kompatybilności z Marketia XML Pro:
- OLX Poster tworzy/modyfikuje TYLKO tabele z prefix ``olx_*`` oraz
  ``variant_cache`` i ``schema_migrations`` (nasz prefix logiczny).
- Marketia XML Pro jest właścicielem tabel ``products*``.
- WAL mode obowiązkowy (concurrent reads).
"""
from __future__ import annotations

# Każda migracja = (version:int, sql:str). Aplikowane rosnąco.
# NIGDY nie edytuj historii — dodawaj nową wersję.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS olx_listings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sku             TEXT NOT NULL,
            account_name    TEXT NOT NULL,
            city            TEXT NOT NULL,
            url             TEXT,
            screenshot_path TEXT,
            published_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status          TEXT NOT NULL DEFAULT 'active'
        );
        CREATE INDEX IF NOT EXISTS idx_olx_listings_sku      ON olx_listings(sku);
        CREATE INDEX IF NOT EXISTS idx_olx_listings_account  ON olx_listings(account_name);
        CREATE INDEX IF NOT EXISTS idx_olx_listings_status   ON olx_listings(status);

        CREATE TABLE IF NOT EXISTS olx_jobs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sku           TEXT NOT NULL,
            account_name  TEXT NOT NULL,
            city          TEXT NOT NULL,
            scheduled_at  TIMESTAMP,
            status        TEXT NOT NULL DEFAULT 'pending',
            retries       INTEGER NOT NULL DEFAULT 0,
            last_error    TEXT,
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_olx_jobs_status    ON olx_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_olx_jobs_scheduled ON olx_jobs(scheduled_at);

        CREATE TABLE IF NOT EXISTS olx_accounts_meta (
            name                    TEXT PRIMARY KEY,
            warmup_days_remaining   INTEGER NOT NULL DEFAULT 0,
            last_health_check       TIMESTAMP,
            is_paused               INTEGER NOT NULL DEFAULT 0,
            pause_reason            TEXT
        );

        CREATE TABLE IF NOT EXISTS variant_cache (
            hash            TEXT PRIMARY KEY,
            sku             TEXT NOT NULL,
            city            TEXT NOT NULL,
            prompt_version  TEXT NOT NULL,
            variant_json    TEXT NOT NULL,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_variant_cache_sku_city ON variant_cache(sku, city);
        """,
    ),
]
