"""Ban detector — 3-level detection + orkiestrator akcji.

**KRYTYCZNY moduł** — user zdecydował SKIP proxy. Ban_detector jest jedyną
warstwą która wyłapuje sygnał zanim OLX zbanuje wszystkie 3 konta (cascade).

Poziomy:
  Level 1 HTTP: response.status + redirect_to_login
  Level 2 DOM:  CAPTCHA selectors + ban keywords (PL + EN)
  Level 3 Behavioral: 3× fail streak per account

Playbook `BAN_ACTIONS` per reason:
  - pause_account_hours (None = infinite until manual unlock)
  - cascade_pause_others_hours
  - notification urgency (silent/normal/urgent)
  - message template
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..data.shared_db import set_account_pause
from ..queue.state_machine import cascade_pause_pending_jobs
from ..security.vault import load_accounts_encrypted
from ..config import ACCOUNTS_ENCRYPTED_PATH
from .audit_logger import log_ban_action
from .notification import notify

if TYPE_CHECKING:  # pragma: no cover
    from playwright.async_api import Page, Response

__all__ = [
    "BAN_ACTIONS",
    "BanBehavior",
    "check_http_signals",
    "check_dom_signals",
    "trigger_ban_action",
    "ban_behavior",
]

_LOG = logging.getLogger("marketia.monitor.ban_detector")


# --- Level 1: HTTP signals -----------------------------------------------


async def check_http_signals(response: "Response | None") -> str | None:
    """Sprawdza response.status + URL redirect. Zwraca reason string lub None.

    Wywoływane po każdym `page.goto()`. Response=None (offline?) → None (nie
    fabrykuj bana z braku sieci).
    """
    if response is None:
        return None

    status = getattr(response, "status", 0)
    if status == 403:
        return "http_403"
    if status == 429:
        return "http_429_rate_limit"
    if 500 <= status < 600:
        return f"http_5xx_{status}"

    # Redirect do /zaloguj = session invalidated = soft ban / session expired.
    url = getattr(response, "url", "") or ""
    if url.startswith("https://www.olx.pl/zaloguj") or url.startswith(
        "https://www.olx.pl/mojolx"
    ):
        return "redirect_to_login"

    return None


# --- Level 2: DOM signals ------------------------------------------------


_CAPTCHA_SELECTORS: tuple[str, ...] = (
    '[data-testid="captcha"]',
    'div[class*="captcha"]',
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'div[class*="cf-challenge"]',  # Cloudflare
)

_BAN_KEYWORDS: tuple[str, ...] = (
    "konto zostało zablokowane",
    "konto zablokowane",
    "account has been blocked",
    "twoje konto zostało zawieszone",
    "podejrzana aktywność",
    "suspicious activity",
    "konto zawieszone",
)

_RATE_LIMIT_KEYWORDS: tuple[str, ...] = (
    "zbyt wiele prób",
    "spróbuj ponownie później",
    "rate limit exceeded",
    "too many requests",
)


async def check_dom_signals(page: "Page | None") -> str | None:
    """Sprawdza DOM po załadowaniu strony. Zwraca reason string lub None."""
    if page is None:
        return None

    # 1. CAPTCHA present (selectors check)
    for sel in _CAPTCHA_SELECTORS:
        try:
            count = await page.locator(sel).count()
        except Exception:
            count = 0
        if count > 0:
            return "captcha_detected"

    # 2. Body text keyword scan
    try:
        body_text = await page.content()
    except Exception as exc:
        _LOG.debug("check_dom_signals: page.content failed: %s", exc)
        return None
    body_lower = body_text.lower()

    for kw in _BAN_KEYWORDS:
        if kw in body_lower:
            return f"ban_keyword:{kw[:30]}"

    for kw in _RATE_LIMIT_KEYWORDS:
        if kw in body_lower:
            return f"rate_limit_keyword:{kw[:30]}"

    return None


# --- Level 3: Behavioral --------------------------------------------------


class BanBehavior:
    """Fail streak tracker — 3× fail w rzędzie = alert.

    Instancja per-process. Reset ręczny przez `record_success`.
    """

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self._fail_streak: dict[str, int] = {}

    def record_success(self, account: str) -> None:
        self._fail_streak[account] = 0

    def record_fail(self, account: str, reason: str = "") -> bool:
        """Zwraca True gdy osiągnięto próg alertu."""
        self._fail_streak[account] = self._fail_streak.get(account, 0) + 1
        n = self._fail_streak[account]
        _LOG.debug("ban_behavior: %s fail_streak=%d reason=%s", account, n, reason)
        return n >= self.threshold

    def get_fail_streak(self, account: str) -> int:
        return self._fail_streak.get(account, 0)


# Global singleton — importowany przez health_check, listing_creator, workers.
ban_behavior = BanBehavior()


# --- Playbook -------------------------------------------------------------


BAN_ACTIONS: dict[str, dict[str, Any]] = {
    "captcha_detected": {
        "pause_account_hours": None,  # infinite dopóki user nie rozwiąże
        "cascade_pause_others_hours": 4,
        "notification": "urgent",
        "message": "CAPTCHA na {account} — rozwiąż ręcznie w otwartym browserze",
        "kill_switch_prompt": True,
    },
    "http_403": {
        "pause_account_hours": 24,
        "cascade_pause_others_hours": 6,
        "notification": "urgent",
        "message": "HTTP 403 na {account} — możliwy ban IP lub konta",
    },
    "http_429_rate_limit": {
        "pause_account_hours": 1,
        "cascade_pause_others_hours": 1,
        "notification": "normal",
        "message": "Rate limit na {account} — pauza 1h, delays x2",
        "modify_delays_multiplier": 2.0,
    },
    "redirect_to_login": {
        "pause_account_hours": 0,  # nie pauzujemy — próba re-login
        "cascade_pause_others_hours": 0,
        "notification": "normal",
        "message": "Session expired na {account} — trigger re-login",
        "trigger_relogin": True,
    },
    "ban_keyword": {
        "pause_account_hours": 24 * 7,  # 7 dni pauza
        "cascade_pause_others_hours": 12,
        "notification": "urgent",
        "message": "SZLABAN wykryty na {account} — sprawdz konto recznie",
        "kill_switch_prompt": True,
    },
    "rate_limit_keyword": {
        "pause_account_hours": 2,
        "cascade_pause_others_hours": 1,
        "notification": "normal",
        "message": "Rate limit keyword na {account} — pauza 2h",
    },
    "http_5xx": {
        "pause_account_hours": 0,  # nie pauzujemy, retry z backoff
        "cascade_pause_others_hours": 0,
        "notification": "silent",
        "message": "OLX 5xx na {account} — retry (transient)",
        "retry_with_backoff": True,
    },
    "3_fails_in_row": {
        "pause_account_hours": 4,
        "cascade_pause_others_hours": 2,
        "notification": "urgent",
        "message": "3x fail na {account} — pauza 4h + cascade 2h",
    },
}


def _resolve_action(reason: str) -> tuple[str, dict[str, Any]]:
    """Mapuje reason string na klucz playbooka + zwraca action dict.

    Klucze w BAN_ACTIONS to prefiksy — np. `ban_keyword:...` mapuje na
    `ban_keyword`, `http_5xx_502` → `http_5xx`.
    """
    # Sprawdz prefix dopasowania (kolejność: najbardziej specyficzne pierwsze)
    for key in ("captcha_detected", "http_403", "http_429_rate_limit",
                "redirect_to_login", "3_fails_in_row"):
        if reason == key:
            return key, BAN_ACTIONS[key]
    # Prefixy z separatorami
    if reason.startswith("ban_keyword"):
        return "ban_keyword", BAN_ACTIONS["ban_keyword"]
    if reason.startswith("rate_limit_keyword"):
        return "rate_limit_keyword", BAN_ACTIONS["rate_limit_keyword"]
    if reason.startswith("http_5xx"):
        return "http_5xx", BAN_ACTIONS["http_5xx"]
    # Default: traktuj jako transient 5xx (retry-friendly)
    _LOG.warning("_resolve_action: nieznany reason %r → default http_5xx", reason)
    return "http_5xx", BAN_ACTIONS["http_5xx"]


def _all_other_accounts(account: str) -> list[str]:
    """Zwraca listę pozostałych kont (do cascade)."""
    try:
        accounts = load_accounts_encrypted(ACCOUNTS_ENCRYPTED_PATH)
    except FileNotFoundError:
        return []
    except Exception as exc:  # pragma: no cover
        _LOG.warning("cannot load accounts for cascade: %s", exc)
        return []
    return [n for n in accounts.keys() if n != account]


async def trigger_ban_action(
    account: str,
    reason: str,
    on_kill_switch_prompt: Any = None,
) -> dict[str, Any]:
    """Główny orchestrator — pauza konta, cascade, notification, audit.

    Args:
        account: konto na którym wykryto sygnał.
        reason: klucz z BAN_ACTIONS lub prefiksowany (`ban_keyword:...`).
        on_kill_switch_prompt: opcjonalny callback dla GUI modal (Faza 4 GUI
            integracja).

    Returns:
        dict z podsumowaniem akcji (dla loggera + testów).
    """
    key, action = _resolve_action(reason)

    now = datetime.utcnow()
    pause_hours = action.get("pause_account_hours")
    cascade_hours = int(action.get("cascade_pause_others_hours") or 0)

    # 1. Pauza konta
    action_taken_parts: list[str] = []
    if pause_hours is None:
        set_account_pause(account, is_paused=True, reason=f"{key} (infinite)")
        action_taken_parts.append("account_paused_infinite")
    elif pause_hours > 0:
        set_account_pause(account, is_paused=True, reason=f"{key} for {pause_hours}h")
        action_taken_parts.append(f"account_paused_{pause_hours}h")

    # 2. Cascade pause pozostałych kont
    cascade_accounts: list[str] = []
    cascade_paused_jobs = 0
    if cascade_hours > 0:
        cascade_accounts = _all_other_accounts(account)
        cascade_until = now + timedelta(hours=cascade_hours)
        for other in cascade_accounts:
            set_account_pause(
                other, is_paused=True, reason=f"cascade_from_{account}"
            )
        cascade_paused_jobs = cascade_pause_pending_jobs(
            cascade_accounts,
            until=cascade_until,
            reason=f"cascade_from_{account}",
        )
        action_taken_parts.append(
            f"cascade_paused_{len(cascade_accounts)}_accounts_{cascade_hours}h"
        )

    # 3. Notification
    urgency = action.get("notification", "silent")
    message = str(action.get("message", "")).format(account=account)
    if urgency == "urgent":
        notify(
            title=f"Ban risk: {account}",
            subtitle=key,
            message=message,
            urgency="urgent",
        )
    elif urgency == "normal":
        notify(title="Ban signal", message=message, urgency="normal")
    elif urgency == "silent":
        # silent = tylko log, bez macOS notification
        _LOG.info("ban silent: %s reason=%s msg=%s", account, key, message)

    # 4. Audit log
    log_ban_action(
        account=account,
        reason=reason,
        action_taken=",".join(action_taken_parts) or "none",
        cascade_accounts=cascade_accounts,
    )

    # 5. Kill switch prompt (GUI modal callback, opcjonalny)
    if action.get("kill_switch_prompt") and on_kill_switch_prompt is not None:
        try:
            on_kill_switch_prompt(account, reason, message)
        except Exception:  # pragma: no cover
            _LOG.exception("kill_switch_prompt callback failed")

    return {
        "account": account,
        "reason": reason,
        "action_key": key,
        "pause_hours": pause_hours,
        "cascade_accounts": cascade_accounts,
        "cascade_paused_jobs": cascade_paused_jobs,
        "urgency": urgency,
    }
