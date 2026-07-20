"""Kill switch — panic button STOP ALL.

Zatrzymuje wszystkie aktywne workery, cancelluje pending jobs, pauzuje konta.

Graceful termination: workery sprawdzają `is_kill_switch_active()` w każdej
iteracji i wychodzą po aktualnym kroku (nie mid-form).

Deactivate NIE odblokuje kont — user musi świadomie każde konto odblokować
w GUI Konta (żeby uniknąć przypadku "kliknąłem STOP ALL, potem odkliknąłem,
dalej leci").
"""
from __future__ import annotations

import logging

from ..data.shared_db import get_connection
from ..queue.state_machine import JobStatus
from .audit_logger import log_event
from .notification import notify

__all__ = [
    "kill_switch_activate",
    "kill_switch_deactivate",
    "is_kill_switch_active",
]

_LOG = logging.getLogger("marketia.monitor.kill_switch")

# Global flag — workery sprawdzają co iterację.
_KILL_FLAG: bool = False


def is_kill_switch_active() -> bool:
    """Sprawdź w każdej iteracji worker loopa. Cheap read (bool)."""
    return _KILL_FLAG


def kill_switch_activate(reason: str = "user_action") -> dict[str, int]:
    """Aktywuje kill switch — STOP ALL.

    Kroki:
      1. Ustawia globalną flagę → workery przerywają po aktualnym kroku.
      2. Cancel wszystkich PENDING i SCHEDULED_LATER jobs (transition → CANCELED).
      3. Pauzuje wszystkie konta w olx_accounts_meta.
      4. macOS notification (urgent + Sosumi).
      5. Audit log event.

    Returns:
        dict {"canceled_jobs": int, "paused_accounts": int}
    """
    global _KILL_FLAG
    _KILL_FLAG = True
    _LOG.warning("KILL SWITCH ACTIVATED: %s", reason)

    canceled = 0
    paused = 0
    with get_connection() as conn:
        # Cancel pending + scheduled_later
        cur = conn.execute(
            """
            UPDATE olx_jobs
            SET status = ?, last_error = ?
            WHERE status IN (?, ?)
            """,
            (
                JobStatus.CANCELED.value,
                f"kill_switch: {reason}",
                JobStatus.PENDING.value,
                JobStatus.SCHEDULED_LATER.value,
            ),
        )
        canceled = int(cur.rowcount or 0)

        # Pause wszystkie konta
        cur = conn.execute(
            """
            UPDATE olx_accounts_meta
            SET is_paused = 1, pause_reason = ?
            """,
            (f"kill_switch: {reason}",),
        )
        paused = int(cur.rowcount or 0)

    log_event(
        "kill_switch_activated",
        reason=reason,
        canceled_jobs=canceled,
        paused_accounts=paused,
    )

    notify(
        title="STOP ALL activated",
        message=f"Anulowano {canceled} zadan, spauzowano {paused} kont.",
        urgency="urgent",
    )

    return {"canceled_jobs": canceled, "paused_accounts": paused}


def kill_switch_deactivate(user_confirmed: bool = False) -> None:
    """Deaktywuje kill switch.

    UWAGA: NIE odblokuje kont automatycznie ani nie wznowi jobs. User musi
    świadomie każde konto odblokować w GUI Konta.

    Args:
        user_confirmed: musi być True (guard przed niezamierzonym release).

    Raises:
        RuntimeError: gdy user_confirmed=False.
    """
    global _KILL_FLAG
    if not user_confirmed:
        raise RuntimeError("kill_switch_deactivate wymaga user_confirmed=True")

    _KILL_FLAG = False
    _LOG.info("Kill switch deactivated by user")

    log_event("kill_switch_deactivated", reason="user_confirmed")

    notify(
        title="Kill switch disabled",
        message="Konta nadal spauzowane. Odblokuj recznie w Konta.",
        urgency="normal",
    )
