"""PJS ("Zapłać jeśli sprzedasz") toggle enforcement.

Business rule z SPEC: **ZAWSZE aktywny PJS przed submitem**. Bez PJS ogłoszenie
jest płatne z góry — niedopuszczalne w naszym flow dropshippingu.

⚠️  TO_VERIFY: DOM struktura toggle — na OLX bywa różnie:
    - ``button[aria-pressed]`` z tekstem "Zapłać jeśli sprzedasz",
    - ``input[type=checkbox]`` w labelu,
    - custom komponent z ``data-checked`` / ``data-active`` / ``.active`` class.

Kod sprawdza wszystkie 3 warianty przez ``_is_active()`` heurystykę.

Jeśli toggle nie istnieje w formularzu → ``PJSUnavailable`` — kategoria nie
obsługuje PJS, wtedy WYŻSZA WARSTWA anuluje wystawienie (nie submitujemy jako
płatne).
"""
from __future__ import annotations

import sys
import traceback

from playwright.async_api import Locator, Page

from .humanizer import human_action_pause, human_click
from .selector_registry import SelectorMissing, resolve

__all__ = [
    "ensure_pjs_active",
    "PJSUnavailable",
]


class PJSUnavailable(Exception):
    """Toggle "Zapłać jeśli sprzedasz" nieobecny — kategoria nie wspiera PJS."""


async def _is_active(locator: Locator) -> bool | None:
    """Zwraca True/False jeśli można ustalić stan, None gdy niepewne.

    Sprawdza kolejno:
        1. ``aria-pressed=true`` (button role=switch).
        2. ``data-checked=true`` / ``data-active=true``.
        3. ``input`` w środku ``:checked``.
        4. class name zawiera ``active`` / ``checked`` / ``on``.

    Niepewność (None) traktujemy defensywnie: jak "nieaktywny" → klikamy.
    """
    try:
        # 1. aria-pressed
        aria = await locator.get_attribute("aria-pressed")
        if aria is not None:
            return aria.lower() == "true"

        # 2. data-checked / data-active
        for attr in ("data-checked", "data-active", "data-state"):
            val = await locator.get_attribute(attr)
            if val is not None:
                v = val.lower()
                if v in ("true", "on", "active", "checked"):
                    return True
                if v in ("false", "off", "inactive", "unchecked"):
                    return False

        # 3. input[:checked] w środku (label wrapping input)
        try:
            checked = await locator.locator("input").first.is_checked(timeout=500)
            return bool(checked)
        except Exception:
            pass

        # 4. class name heuristic
        cls = await locator.get_attribute("class") or ""
        cls_l = cls.lower()
        if any(marker in cls_l for marker in ("active", "checked", "enabled-on", "is-on")):
            return True
        if any(marker in cls_l for marker in ("inactive", "unchecked", "disabled-off", "is-off")):
            return False

        return None
    except Exception:
        traceback.print_exc(file=sys.stdout)
        return None


async def ensure_pjs_active(page: Page) -> bool:
    """Znajduje toggle PJS i włącza jeśli nie jest aktywny.

    Post-condition: PJS aktywny (True) lub ``PJSUnavailable`` raised.

    Args:
        page: Playwright ``Page`` — formularz OLX ``/dodaj/`` po wypełnieniu
            podstawowych pól (przed submitem).

    Returns:
        True zawsze przy sukcesie.

    Raises:
        PJSUnavailable: gdy toggle brakuje w formularzu (np. kategoria bez PJS).
    """
    # 1. Zresolvuj toggle. SelectorMissing → PJSUnavailable (kategoria nie ma toggle).
    try:
        toggle = await resolve(page, "pjs_toggle", timeout=6000)
    except SelectorMissing as exc:
        raise PJSUnavailable(
            "Toggle 'Zapłać jeśli sprzedasz' nieobecny — kategoria nie wspiera PJS."
        ) from exc

    # Scroll do widoku (long forms — toggle poza viewport).
    try:
        await toggle.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass

    # 2. Sprawdź stan.
    state = await _is_active(toggle)
    if state is True:
        print("[pjs] toggle już aktywny — pomijam click", flush=True)
        return True

    # 3. Kliknij. Używamy humanized click (mouse move + offset).
    #    Musimy podać selector do human_click — używamy pierwszego z registry.
    from .selector_registry import SELECTORS

    click_selector = SELECTORS["pjs_toggle"][0]  # data-testid → najbardziej stabilny
    try:
        await human_click(page, click_selector)
    except Exception:
        # Fallback: bezpośredni click na locator.
        try:
            await toggle.click(timeout=5000)
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise PJSUnavailable(f"Toggle znaleziony ale click failed: {exc}") from exc

    # 4. Krótka pauza żeby state się zapropagował.
    await human_action_pause(0.4, 1.2)

    # 5. Post-check.
    new_state = await _is_active(toggle)
    if new_state is False:
        # Jeszcze jedna próba — czasem pierwszy click otwiera modal potwierdzający.
        print("[pjs] po klick stan wciąż nieaktywny — druga próba", flush=True)
        try:
            await toggle.click(timeout=3000)
            await human_action_pause(0.3, 0.9)
            new_state = await _is_active(toggle)
        except Exception:
            traceback.print_exc(file=sys.stdout)

    if new_state is False:
        raise PJSUnavailable(
            "Toggle PJS nie chciał się przełączyć — możliwe że kategoria wymusza "
            "płatne wystawienie lub OLX zmienił mechanikę toggle."
        )

    # None (niepewne) lub True → traktuj jako OK. Post-verification zrobi
    # listing_creator (screenshot pre-submit).
    return True
