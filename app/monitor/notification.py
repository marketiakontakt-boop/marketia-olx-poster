"""macOS native notifications via osascript (bez extra deps).

Fallback pozostawiony na potem: pync/plyer (wymaga py-obc-framework instalacji).

Uwaga: notification nigdy nie rzuca wyjątku — DND active, brak dźwięku,
system reject → tylko log warning. Wywołania są best-effort.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Literal

__all__ = [
    "notify",
    "notify_ban_alert",
    "notify_daily_report",
    "notify_captcha",
    "Urgency",
]

_LOG = logging.getLogger("marketia.monitor.notification")

Urgency = Literal["silent", "normal", "urgent"]

# Mapowanie urgency → nazwa sound file macOS.
# silent → brak dźwięku (banner-only). urgent → gniewny alert (Sosumi).
_SOUND_MAP: dict[str, str | None] = {
    "silent": None,
    "normal": "Ping",
    "urgent": "Sosumi",
}


def notify(
    title: str,
    message: str,
    urgency: Urgency = "normal",
    subtitle: str | None = None,
) -> None:
    """Wyślij macOS notification przez osascript.

    Nie rzuca wyjątku przy błędzie — loguje tylko. Notification to nie
    must-have. System może być bez dźwięku, DND active itd.

    Args:
        title: krótki tytuł (max ~50 znaków wyświetlone).
        message: treść (wrap do ~3 linii).
        urgency: silent/normal/urgent — mapuje na sound.
        subtitle: opcjonalny podtytuł (macOS 10.9+).
    """
    safe_title = _escape(title)
    safe_message = _escape(message)
    parts = [
        f'display notification "{safe_message}"',
        f'with title "{safe_title}"',
    ]

    if subtitle:
        parts.append(f'subtitle "{_escape(subtitle)}"')

    sound = _SOUND_MAP.get(urgency)
    if sound:
        parts.append(f'sound name "{sound}"')

    script = " ".join(parts)

    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            timeout=5,
            capture_output=True,
        )
        _LOG.debug("notification sent: %r", title)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ) as e:
        _LOG.warning("notification failed (osascript): %s", e)


def _escape(text: str) -> str:
    """Escape dla AppleScript strings.

    Kolejność MA znaczenie:
      1. najpierw \\ (żeby nie zjeść potem naszych własnych escape-ów)
      2. potem "
    """
    return text.replace("\\", "\\\\").replace('"', '\\"')


# --- Convenience: high-level events -----------------------------------------


def notify_ban_alert(account: str, reason: str, message: str) -> None:
    """Ban risk detected — urgent + z dźwiękiem Sosumi."""
    notify(
        title=f"Ban risk: {account}",
        subtitle=reason,
        message=message,
        urgency="urgent",
    )


def notify_daily_report(counts: dict[str, int]) -> None:
    """Codzienne podsumowanie o 22:00 — silent."""
    text = "  ".join(f"{k}: {v}" for k, v in counts.items())
    notify(
        title="Marketia OLX — raport dnia",
        message=text or "brak zdarzeń",
        urgency="silent",
    )


def notify_captcha(account: str) -> None:
    """CAPTCHA wykryta — urgent, user musi zareagować."""
    notify(
        title=f"CAPTCHA: {account}",
        message="Konto pauzowane. Otwórz browser i rozwiąż ręcznie.",
        urgency="urgent",
    )
