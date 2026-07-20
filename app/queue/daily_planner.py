"""Daily planner — staggered slots per konto (BEZ PROXY).

Decyzja user-a (2026-07-17): zamiast per-account okno 8-22, każde konto ma
osobny 3-godzinny slot bez czasowego overlap. Fingerprint z jednego IP domowego
wygląda jak jeden human user w 3 sesjach.

Sloty:
    marketia-glowne    08:00 - 11:30  (3.5h)  cap 12 / dzień
    marketia-warszawa  14:00 - 17:30  (3.5h)  cap 10 / dzień
    marketia-krakow    19:00 - 22:00  (3h)    cap 8  / dzień

Weekend:
    - Sobota: slot +2h opóźnienie, cap × 0.6
    - Niedziela: slot +3h opóźnienie, cap × 0.3

Warmup (dla nowych kont): 20% / 50% / 75% / 100% cap w zależności od
``warmup_days_remaining``.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta
from typing import Optional

__all__ = [
    "ACCOUNT_WINDOWS",
    "DAILY_CAPS",
    "plan_account_daily",
    "apply_warmup_cap",
    "apply_weekend_pattern",
    "is_weekend",
    "get_window_for_day",
]

_LOG = logging.getLogger("marketia.queue.daily_planner")


#: Dzienne okna per konto (start, end) — DZIEŃ POWSZEDNI.
ACCOUNT_WINDOWS: dict[str, tuple[time, time]] = {
    "marketia-glowne": (time(8, 0), time(11, 30)),
    "marketia-warszawa": (time(14, 0), time(17, 30)),
    "marketia-krakow": (time(19, 0), time(22, 0)),
}


#: Bazowy dzienny cap ogłoszeń per konto (warmup=0).
DAILY_CAPS: dict[str, int] = {
    "marketia-glowne": 12,
    "marketia-warszawa": 10,
    "marketia-krakow": 8,
}


#: Weekend multipliers dla capa.
WEEKEND_MULTIPLIER: dict[int, float] = {
    5: 0.6,  # Saturday
    6: 0.3,  # Sunday
}


#: Opóźnienie startu slotu w weekend (godziny).
WEEKEND_START_DELAY_HOURS: dict[int, int] = {
    5: 2,  # Saturday
    6: 3,  # Sunday
}


# --- Helpers --------------------------------------------------------------

def is_weekend(day: date) -> bool:
    """True dla soboty (5) i niedzieli (6)."""
    return day.weekday() >= 5


def get_window_for_day(
    account_name: str,
    day: date,
) -> tuple[datetime, datetime]:
    """Zwraca (start_dt, end_dt) dla konta w danym dniu z weekend delay.

    Raises:
        KeyError: gdy konto nie ma zdefiniowanego okna.
    """
    if account_name not in ACCOUNT_WINDOWS:
        raise KeyError(f"Brak ACCOUNT_WINDOWS dla '{account_name}'")

    start_t, end_t = ACCOUNT_WINDOWS[account_name]
    start_dt = datetime.combine(day, start_t)
    end_dt = datetime.combine(day, end_t)

    delay_h = WEEKEND_START_DELAY_HOURS.get(day.weekday(), 0)
    if delay_h > 0:
        start_dt += timedelta(hours=delay_h)
        end_dt += timedelta(hours=delay_h)
        # 22:00 hard cap — nie idziemy po 23:00.
        max_end = datetime.combine(day, time(23, 0))
        if end_dt > max_end:
            end_dt = max_end
    return start_dt, end_dt


def apply_weekend_pattern(base_cap: int, day: date) -> int:
    """Cap × weekend multiplier (0.6 sob, 0.3 ndz). Min 1 gdy base > 0."""
    if base_cap <= 0:
        return 0
    mult = WEEKEND_MULTIPLIER.get(day.weekday(), 1.0)
    return max(1, int(base_cap * mult))


def apply_warmup_cap(
    account_name: str,
    base_cap: int,
    warmup_days_remaining: int,
) -> int:
    """Warmup 7-dniowy dla nowych kont.

    - dni 6-7: 20% (start warmup)
    - dni 3-5: 50%
    - dni 1-2: 75%
    - dzień 0: 100%
    """
    if base_cap <= 0:
        return 0
    if warmup_days_remaining <= 0:
        return base_cap
    if warmup_days_remaining >= 6:
        return max(1, int(base_cap * 0.2))
    if warmup_days_remaining >= 3:
        return max(1, int(base_cap * 0.5))
    return max(1, int(base_cap * 0.75))


# --- Main planner ---------------------------------------------------------

def plan_account_daily(
    account_name: str,
    jobs_count: int,
    today: Optional[date] = None,
    rng_seed: Optional[int] = None,
) -> list[datetime]:
    """Rozkłada N ogłoszeń w slocie konta z jitter ±30% i długą przerwą w środku.

    Slot dłuższy niż 3h ma 1 long break 15-30 min (na środku).
    Min interval 3 min pomiędzy jobs.

    Args:
        account_name: nazwa konta (musi być w ACCOUNT_WINDOWS).
        jobs_count: liczba ogłoszeń do rozłożenia (>= 0).
        today: opcjonalna data (default: dzisiejsza).
        rng_seed: opcjonalne seed do testów deterministic.

    Returns:
        list[datetime] posortowana rosnąco. Może zwrócić mniej niż jobs_count
        jeśli slot się wyczerpie.
    """
    if jobs_count <= 0:
        return []

    if account_name not in ACCOUNT_WINDOWS:
        _LOG.warning("plan_account_daily: nieznane konto '%s'", account_name)
        return []

    day = today or date.today()
    rng = random.Random(rng_seed) if rng_seed is not None else random.Random()

    start_dt, end_dt = get_window_for_day(account_name, day)
    # Losowy start-offset 0-15 min (dodatkowo randomizacja "punktualności").
    start_dt = start_dt.replace(minute=start_dt.minute + rng.randint(0, 15))

    slot_minutes = int((end_dt - start_dt).total_seconds() / 60)
    if slot_minutes <= 0:
        _LOG.warning(
            "plan_account_daily: slot pusty dla %s (%s..%s)",
            account_name,
            start_dt,
            end_dt,
        )
        return []

    base_interval = slot_minutes / jobs_count

    schedule: list[datetime] = []
    current = start_dt

    for i in range(jobs_count):
        # jitter ±30% (a nie ±3% jak by można było skopiować bugowo)
        jitter = base_interval * rng.uniform(-0.3, 0.3)
        interval = max(base_interval + jitter, 3.0)
        current += timedelta(minutes=interval)

        if current > end_dt:
            _LOG.debug(
                "slot exhausted at job %d/%d for %s",
                i + 1,
                jobs_count,
                account_name,
            )
            break

        # Long break in the middle of slot (slots > 3h only).
        if i > 0 and i == jobs_count // 2 and slot_minutes > 180:
            long_break = rng.uniform(15, 30)
            current += timedelta(minutes=long_break)
            if current > end_dt:
                break

        schedule.append(current)

    return schedule
