"""Queue package.

Faza 3: state_machine, daily_planner, job_scheduler, retry_manager gotowe.
"""

from .daily_planner import (
    ACCOUNT_WINDOWS,
    DAILY_CAPS,
    apply_warmup_cap,
    apply_weekend_pattern,
    is_weekend,
    plan_account_daily,
)
from .job_scheduler import (
    count_jobs_for_account_today,
    enqueue_variants,
    pick_next_job,
    run_pending_jobs_for_account,
)
from .retry_manager import (
    DEAD_LETTER_LOG,
    next_backoff_delay,
    record_dead_letter,
    schedule_retry,
    should_retry,
)
from .state_machine import (
    MAX_RETRIES,
    RETRY_BACKOFF_MINUTES,
    VALID_TRANSITIONS,
    JobStatus,
    JobTransitionError,
    cascade_pause_pending_jobs,
    count_by_status,
    get_jobs_by_account_and_status,
    get_next_pending_job,
    handle_running_job_result,
    transition_job,
)

__all__ = [
    # state_machine
    "JobStatus",
    "JobTransitionError",
    "VALID_TRANSITIONS",
    "transition_job",
    "handle_running_job_result",
    "count_by_status",
    "get_jobs_by_account_and_status",
    "get_next_pending_job",
    "cascade_pause_pending_jobs",
    "MAX_RETRIES",
    "RETRY_BACKOFF_MINUTES",
    # daily_planner
    "ACCOUNT_WINDOWS",
    "DAILY_CAPS",
    "plan_account_daily",
    "apply_warmup_cap",
    "apply_weekend_pattern",
    "is_weekend",
    # job_scheduler
    "enqueue_variants",
    "pick_next_job",
    "run_pending_jobs_for_account",
    "count_jobs_for_account_today",
    # retry_manager
    "should_retry",
    "next_backoff_delay",
    "schedule_retry",
    "record_dead_letter",
    "DEAD_LETTER_LOG",
]
