"""Humanizer — losowe opóźnienia, variable-speed typing, ludzkie kliknięcia.

Cel: minimalizacja fingerprintu automatyzacji. Sygnały bota które
neutralizujemy:

- Regularny odstęp między ogłoszeniami (uniform 90-240s).
- Constant typing speed (WPM 40-80 + 2% typo + 5% thinking pause).
- Pixel-perfect kliknięcia w centrum elementu (offset ±5px + mouse move).

Wszystkie funkcje async — używać w Playwright flow.

**Ważne:** ``human_delay_seconds`` operuje na SEKUNDACH (learning z SPEC:
initial impl używała ms → 90ms zamiast 90s → wykrywalny bot). Nie zmieniać
jednostki.
"""
from __future__ import annotations

import asyncio
import random
import string
from typing import Any

from playwright.async_api import Page

from ..config import HUMAN_DELAY_MAX_S, HUMAN_DELAY_MIN_S

__all__ = [
    "human_delay_seconds",
    "human_action_pause",
    "human_type",
    "human_click",
]


async def human_delay_seconds(
    min_s: int = HUMAN_DELAY_MIN_S,
    max_s: int = HUMAN_DELAY_MAX_S,
) -> float:
    """Sleep 90-240 SEKUND (default). Uniform distribution.

    Używane MIĘDZY publikacjami ogłoszeń (staggered scheduling z SPEC 15 R2).
    Zwraca faktyczny czas snu (dla logów).
    """
    if min_s > max_s:
        min_s, max_s = max_s, min_s
    delay = random.uniform(float(min_s), float(max_s))
    await asyncio.sleep(delay)
    return delay


async def human_action_pause(
    min_s: float = 0.5,
    max_s: float = 3.0,
) -> float:
    """Krótka pauza W OBRĘBIE jednego formularza (między krokami).

    Używać po ``goto()``, przed submitem, między wypełnieniem pól. Nie mylić
    z ``human_delay_seconds`` (delay między ogłoszeniami).
    """
    if min_s > max_s:
        min_s, max_s = max_s, min_s
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)
    return delay


async def human_type(
    page: Page,
    selector: str,
    text: str,
    wpm_range: tuple[int, int] = (40, 80),
) -> None:
    """Variable-speed typing z realistycznymi błędami.

    - Base delay: ``60000 / (wpm * 5)`` ms per znak (avg word = 5 znaków).
    - **2% chance typo + backspace** per znak (random alpha, sleep 0.15-0.4s,
      backspace, sleep 0.1-0.25s).
    - **5% chance thinking pause** 0.5-1.8s (nagle "user się zawahał").

    Klika w pole przed pisaniem (focus).

    Args:
        page: Playwright ``Page``.
        selector: CSS/XPath selektor (już zresolveowany przez selector_registry).
        text: docelowy string do wpisania.
        wpm_range: min/max WPM per znak (losowane RAZ na całe wywołanie).
    """
    wpm = random.randint(wpm_range[0], wpm_range[1])
    base_delay_ms = 60000.0 / (wpm * 5)

    locator = page.locator(selector).first
    await locator.click()  # focus przed pisaniem
    # Krótki settle po focusie.
    await asyncio.sleep(random.uniform(0.08, 0.22))

    for char in text:
        # 5% chance thinking pause PRZED znakiem.
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.5, 1.8))

        # 2% chance typo → backspace.
        if random.random() < 0.02:
            typo = random.choice(string.ascii_lowercase)
            await page.keyboard.type(typo, delay=base_delay_ms)
            await asyncio.sleep(random.uniform(0.15, 0.4))
            await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.1, 0.25))

        # Faktyczny znak — dorzuć ±30% jitter do base delay.
        jitter = random.uniform(0.7, 1.3)
        await page.keyboard.type(char, delay=base_delay_ms * jitter)


async def human_click(page: Page, selector: str) -> None:
    """Realistyczne kliknięcie z ruchem myszy + random offset.

    - Bounding box target → punkt = centrum + offset ``(-5..+5, -5..+5)``.
    - ``mouse.move()`` w 15-40 krokach (z aktualnej pozycji do targetu).
    - Krótka pauza 0.1-0.4s po ruchu, przed samym ``click()``.

    Fallback: gdy element nie ma bounding_box (invisible / off-screen) →
    delegate do ``locator.click()`` bez humanizacji.
    """
    locator = page.locator(selector).first

    # Poczekaj aż będzie widoczny (max 5s, potem delegat na natywny click).
    try:
        await locator.wait_for(state="visible", timeout=5000)
    except Exception:
        await locator.click()
        return

    box = await locator.bounding_box()
    if box is None:
        # Fallback — bez humanizacji.
        await locator.click()
        return

    target_x = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
    target_y = box["y"] + box["height"] / 2 + random.uniform(-5, 5)

    steps = random.randint(15, 40)
    await page.mouse.move(target_x, target_y, steps=steps)
    await asyncio.sleep(random.uniform(0.1, 0.4))
    await page.mouse.click(target_x, target_y)


# --- Utility ---------------------------------------------------------------

def _describe_delay(min_s: float, max_s: float) -> dict[str, Any]:
    """Debug helper: opis konfiguracji delay dla logów."""
    return {"min_s": min_s, "max_s": max_s, "distribution": "uniform"}
