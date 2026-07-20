"""Centralna konfiguracja aplikacji.

Ścieżki, stałe timingu i klucze API pobierane z .env (python-dotenv).
Zero side-effectów przy imporcie — tylko definicje.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Załaduj .env z root repo (jeśli istnieje). Nie failuje gdy brak.
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)

# --- Ścieżki ---------------------------------------------------------------

#: SQLite shared z Marketia XML Pro. Współdzielony — my ograniczamy się do
#: prefix `olx_*` + `variant_cache` + `schema_migrations`.
DB_PATH: Path = Path("~/Documents/_meta/marketia-shared/products.db").expanduser()

#: Playwright user_data_dir per konto (cookies, localStorage).
PROFILES_DIR: Path = _ROOT / "data" / "profiles"

#: Screenshoty potwierdzenia wystawienia — retencja 30 dni.
SCREENSHOTS_DIR: Path = _ROOT / "output" / "screenshots"

#: Logi (app.log, audit.log, selector_failures.log).
LOGS_DIR: Path = _ROOT / "output" / "logs"

#: Codzienne raporty markdown (22:00 CRON).
REPORTS_DIR: Path = _ROOT / "output" / "reports"

#: Encrypted accounts.json.
ACCOUNTS_ENCRYPTED_PATH: Path = _ROOT / "data" / "accounts.json.encrypted"

#: City templates (niezaszyfrowany, brak PII).
CITY_TEMPLATES_PATH: Path = _ROOT / "data" / "city_templates.json"

# --- Stałe ----------------------------------------------------------------

#: Wersja promptów AI + logiki wariantów. Zmiana → cache invalidation przy
#: odczycie (variant_cache_get zwraca None gdy row.prompt_version != obecna).
PROMPT_VERSION: str = "olx-v1"

#: Random delay pomiędzy ogłoszeniami — sekundy, nie ms.
HUMAN_DELAY_MIN_S: int = 90
HUMAN_DELAY_MAX_S: int = 240

#: Wartość dziennego cap (fallback gdy account.daily_limit brak).
DEFAULT_DAILY_LIMIT: int = 15

#: Warmup dla nowych kont.
DEFAULT_WARMUP_DAYS: int = 7

# --- Keychain --------------------------------------------------------------

KEYCHAIN_SERVICE: str = "marketia-olx-poster"
KEYCHAIN_MASTER_KEY_USERNAME: str = "master-key"

# --- Feature flags ---------------------------------------------------------

ENABLE_VISION_FALLBACK: bool = os.getenv("ENABLE_VISION_FALLBACK", "false").lower() == "true"
ENABLE_GEMINI_VARIANTS: bool = os.getenv("ENABLE_GEMINI_VARIANTS", "true").lower() == "true"

# --- Klucze API ------------------------------------------------------------

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# --- Logi ------------------------------------------------------------------

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


def ensure_dirs() -> None:
    """Upewnij się że wszystkie output/data dirs istnieją. Wywołaj przy starcie GUI."""
    for p in (PROFILES_DIR, SCREENSHOTS_DIR, LOGS_DIR, REPORTS_DIR, DB_PATH.parent):
        p.mkdir(parents=True, exist_ok=True)


def proxy_for_account(account_name: str) -> str | None:
    """Zwraca proxy URL z .env dla konta lub None gdy brak.

    Konwencja: env key = ``OLX_PROXY_`` + upper(account_name.replace('-', '_')).
    """
    key = f"OLX_PROXY_{account_name.upper().replace('-', '_')}"
    val = os.getenv(key)
    return val if val else None
