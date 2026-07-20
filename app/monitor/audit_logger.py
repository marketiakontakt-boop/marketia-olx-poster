"""Audit logger — append-only, structured JSON per line, PII redakcja.

Log w `output/logs/audit.jsonl`. Format: 1 event = 1 linia JSON (JSONL).

PII redakcja obligatoryjna — nawet w logach nie zostawiamy telefonów/emaili
(learning z SPEC sekcja 12).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from ..config import LOGS_DIR

__all__ = [
    "log_event",
    "log_listing_success",
    "log_listing_fail",
    "log_ban_action",
]

_LOG = logging.getLogger("marketia.monitor.audit")

_AUDIT_FILE = LOGS_DIR / "audit.jsonl"

# PII patterns do redakcji.
# Kolejność MA znaczenie: email PRZED phone (żeby "+48" w liczbie po @
# nie łapało się jako phone → w praktyce email pattern jest greedy więc OK).
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Email: word chars z .+- oraz podstawowa strukturalna forma.
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    # Telefon PL: +48 XXX XXX XXX (spacje/myślniki opcjonalne).
    (
        re.compile(r"\+?\d{2}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3}"),
        "[PHONE]",
    ),
    # Kod pocztowy PL: XX-XXX.
    (re.compile(r"\b\d{2}-\d{3}\b"), "[POSTAL]"),
]


def _redact(text: str) -> str:
    """Redakcja PII z dowolnego stringa.

    Idempotentna — po pierwszym przejściu placeholdery [EMAIL] etc już nie
    matchują żadnego wzorca (bo nie mają @ ani cyfr w odpowiednich pozycjach).
    """
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def log_event(event_type: str, **kwargs: Any) -> None:
    """Zapisz event do audit log. Wszystkie string values są redagowane.

    Streaming save: open + write + close per event (atomicity per line).
    Rescue: gdy write failuje — log error, ale nie rzuca (audit nie może
    zabić głównego workflow).
    """
    _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "type": event_type,
    }
    for k, v in kwargs.items():
        if isinstance(v, str):
            payload[k] = _redact(v)
        elif isinstance(v, list):
            payload[k] = [_redact(x) if isinstance(x, str) else x for x in v]
        else:
            payload[k] = v

    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        _LOG.error("audit log JSON serialize failed: %s (event=%s)", exc, event_type)
        return

    try:
        with _AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        _LOG.error("audit log write failed: %s", exc)


def log_listing_success(
    sku: str,
    account: str,
    city: str,
    url: str,
    screenshot: str | None = None,
) -> None:
    """Sukces publikacji ogłoszenia."""
    log_event(
        "listing_success",
        sku=sku,
        account=account,
        city=city,
        url=url,
        screenshot=screenshot,
    )


def log_listing_fail(
    sku: str,
    account: str,
    city: str,
    error: str,
    retries: int = 0,
) -> None:
    """Fail publikacji — z retry counter."""
    log_event(
        "listing_fail",
        sku=sku,
        account=account,
        city=city,
        error=error,
        retries=retries,
    )


def log_ban_action(
    account: str,
    reason: str,
    action_taken: str,
    cascade_accounts: list[str] | None = None,
) -> None:
    """Ban action wykryty i wykonany (pauza + cascade)."""
    log_event(
        "ban_action",
        account=account,
        reason=reason,
        action=action_taken,
        cascade_accounts=cascade_accounts or [],
    )
