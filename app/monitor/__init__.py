"""Monitoring package — Faza 4.

Moduły:
  - notification: macOS notifications (osascript)
  - audit_logger: JSONL append-only + PII redakcja
  - ban_detector: 3-level detection + BAN_ACTIONS playbook
  - kill_switch: STOP ALL panic button
  - health_check: co 30 min monitor per konto
"""

from .audit_logger import (
    log_ban_action,
    log_event,
    log_listing_fail,
    log_listing_success,
)
from .ban_detector import (
    BAN_ACTIONS,
    BanBehavior,
    ban_behavior,
    check_dom_signals,
    check_http_signals,
    trigger_ban_action,
)
from .health_check import (
    HEALTH_CHECK_URL,
    health_check_account,
    run_health_check_all,
    start_health_monitor,
)
from .kill_switch import (
    is_kill_switch_active,
    kill_switch_activate,
    kill_switch_deactivate,
)
from .notification import (
    Urgency,
    notify,
    notify_ban_alert,
    notify_captcha,
    notify_daily_report,
)

__all__ = [
    # notification
    "notify",
    "notify_ban_alert",
    "notify_captcha",
    "notify_daily_report",
    "Urgency",
    # audit
    "log_event",
    "log_listing_success",
    "log_listing_fail",
    "log_ban_action",
    # ban_detector
    "BAN_ACTIONS",
    "BanBehavior",
    "ban_behavior",
    "check_http_signals",
    "check_dom_signals",
    "trigger_ban_action",
    # kill_switch
    "kill_switch_activate",
    "kill_switch_deactivate",
    "is_kill_switch_active",
    # health_check
    "HEALTH_CHECK_URL",
    "health_check_account",
    "run_health_check_all",
    "start_health_monitor",
]
