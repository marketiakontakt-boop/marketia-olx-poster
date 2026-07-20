"""Health check monitor — co 30 min per konto.

Test `mojolx` endpoint bez wystawiania czegokolwiek. Cel:
  - wykryć CAPTCHA/soft ban ZANIM konto zostanie zbanowane przy próbie
    wystawienia oferty (cascade risk)
  - update `olx_accounts_meta.last_health_check` (dashboard/GUI)
  - reset fail_streak per success (behavioral level)

Nie blokuje worker loops. Uruchamiane jako osobny asyncio task
(`start_health_monitor`).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..data.shared_db import update_last_health_check
from ..security.vault import load_accounts_encrypted, VaultError
from ..config import ACCOUNTS_ENCRYPTED_PATH
from .ban_detector import ban_behavior, check_dom_signals, check_http_signals, trigger_ban_action
from .kill_switch import is_kill_switch_active

if TYPE_CHECKING:  # pragma: no cover
    from ..olx.browser_pool import BrowserPool

__all__ = [
    "health_check_account",
    "start_health_monitor",
    "run_health_check_all",
    "HEALTH_CHECK_URL",
]

_LOG = logging.getLogger("marketia.monitor.health_check")

HEALTH_CHECK_URL: str = "https://www.olx.pl/mojolx"

#: Default interval — 30 min.
DEFAULT_INTERVAL_MINUTES: int = 30


async def health_check_account(
    account: str,
    browser_pool: "BrowserPool",
) -> dict[str, str | None]:
    """Wykonuje pojedynczy health check dla konta.

    Kroki:
      1. Otwórz stronę /mojolx (persistent context — session z profile).
      2. Level 1 HTTP check → trigger ban action jeśli reason.
      3. Level 2 DOM check → trigger ban action jeśli reason.
      4. OK path: update last_health_check + record_success.

    Returns:
        dict {"account": account, "status": "ok"/"ban", "reason": str|None}
    """
    _LOG.info("health_check start: %s", account)
    try:
        context, page = await browser_pool.acquire(account, headless=True)
    except Exception as exc:
        _LOG.warning("health_check: acquire failed for %s: %s", account, exc)
        return {"account": account, "status": "error", "reason": f"acquire:{exc}"}

    try:
        response = await page.goto(
            HEALTH_CHECK_URL,
            wait_until="networkidle",
            timeout=30_000,
        )

        # Level 1
        http_reason = await check_http_signals(response)
        if http_reason:
            await trigger_ban_action(account, http_reason)
            return {"account": account, "status": "ban", "reason": http_reason}

        # Level 2
        dom_reason = await check_dom_signals(page)
        if dom_reason:
            await trigger_ban_action(account, dom_reason)
            return {"account": account, "status": "ban", "reason": dom_reason}

        # OK
        update_last_health_check(account, ts=datetime.now(UTC))
        ban_behavior.record_success(account)
        _LOG.info("health_check ok: %s", account)
        return {"account": account, "status": "ok", "reason": None}

    except Exception as exc:
        traceback.print_exc(file=sys.stdout)
        _LOG.warning("health_check exception for %s: %s", account, exc)
        return {"account": account, "status": "error", "reason": str(exc)}


async def run_health_check_all(browser_pool: "BrowserPool") -> list[dict[str, str | None]]:
    """Health check dla wszystkich kont w vault. Sekwencyjnie (nie parallel —
    unikamy równoczesnych żądań które mogą wyglądać jak burst).
    """
    try:
        accounts = load_accounts_encrypted(ACCOUNTS_ENCRYPTED_PATH)
    except FileNotFoundError:
        _LOG.warning("health_check: brak accounts vault — nic do sprawdzenia")
        return []
    except VaultError as exc:
        _LOG.error("health_check: vault load failed: %s", exc)
        return []

    results: list[dict[str, str | None]] = []
    for account_name in accounts.keys():
        if is_kill_switch_active():
            _LOG.info("health_check: kill switch active — abort loop")
            break
        result = await health_check_account(account_name, browser_pool)
        results.append(result)
        # Delay między kontami żeby nie robić burst-a
        await asyncio.sleep(5)
    return results


async def start_health_monitor(
    browser_pool: "BrowserPool",
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
) -> None:
    """Asyncio task loop — co `interval_minutes` uruchamia health check
    dla wszystkich kont. Kończy się gdy task jest cancelled.

    Uwaga: nie startuj z GUI thread — użyj `asyncio.create_task` w
    dedicated event loop (osobny wątek).
    """
    interval_s = max(60, interval_minutes * 60)
    _LOG.info("health_monitor started (interval=%ds)", interval_s)
    try:
        while True:
            if is_kill_switch_active():
                _LOG.info("health_monitor: kill switch active — skip round")
            else:
                try:
                    await run_health_check_all(browser_pool)
                except Exception:
                    traceback.print_exc(file=sys.stdout)
                    _LOG.exception("health_monitor round crashed — retry after interval")
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        _LOG.info("health_monitor cancelled")
        raise
