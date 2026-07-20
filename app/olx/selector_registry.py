"""Selector registry — mapa CSS/XPath dla OLX form fields z 3-level fallback.

⚠️  TO_VERIFY (wszystkie klucze):
    Wszystkie selektory są **best-guess** na podstawie znanych patternów OLX
    (``data-testid``, ``name=``, XPath text match). Agent NIE ma dostępu do
    live OLX — user MUSI zwalidować przez::

        playwright codegen https://www.olx.pl/dodaj/

    Porównać wygenerowane selektory z ``SELECTORS`` poniżej i zaktualizować
    jeśli różne. Update commituje jako PR + regression test.

Format ``SELECTORS[key] = [primary, secondary, tertiary]`` — próbowane w
kolejności. Wszystkie fail → ``SelectorMissing(key)`` + log do
``output/logs/selector_failures.log`` (JSONL, timestamp + url + html snapshot).
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

from playwright.async_api import Locator, Page

from ..config import LOGS_DIR

__all__ = [
    "SELECTORS",
    "SelectorMissing",
    "resolve",
    "log_selector_failure",
]


# --- Registry --------------------------------------------------------------

#: Mapa selektorów. Kolejność: nowoczesny (data-testid) → semantyczny
#: (name/attr) → strukturalny/tekstowy fallback. Każdy klucz TO_VERIFY.
SELECTORS: dict[str, list[str]] = {
    # Tytuł ogłoszenia (input text, max ~70 znaków).
    "title_input": [
        "[data-testid=title-input]",
        "input[name=title]",
        "form input[type=text]:first-of-type",
    ],
    # Opis (textarea, do ~9000 znaków).
    "description_input": [
        "[data-testid=description-input]",
        "textarea[name=description]",
        "form textarea:first-of-type",
    ],
    # Wybór kategorii (dropdown / autocomplete).
    "category_selector": [
        "[data-testid=category-selector]",
        "[data-cy=category]",
        "div[role=combobox]:has-text('kategori')",
    ],
    # Upload zdjęć (input[type=file], multi).
    "photo_upload": [
        "[data-testid=photo-upload-input]",
        "input[type=file]",
        "input[accept^='image']",
    ],
    # Lokalizacja (autocomplete + wybór z listy).
    "location_input": [
        "[data-testid=location-input]",
        "input[name=location]",
        "input[placeholder*='lokal']",
    ],
    # Cena (numeric input, PLN).
    "price_input": [
        "[data-testid=price-input]",
        "input[name=price]",
        "input[inputmode=numeric]",
    ],
    # Stan: nowe (radio/checkbox).
    "condition_new": [
        "[data-testid=condition-new]",
        "label:has-text('Nowe') input",
        "input[value=new]",
    ],
    # PJS toggle — kluczowe biznesowo (SPEC: ZAWSZE aktywny).
    "pjs_toggle": [
        "[data-testid=pjs-toggle]",
        "button:has-text('Zapłać jeśli sprzedasz')",
        "//button[contains(., 'Zapłać jeśli sprzedasz')]",
    ],
    # Submit — końcowy przycisk "Wystaw ogłoszenie".
    "submit_button": [
        "[data-testid=submit-button]",
        "button[type=submit]:has-text('Wystaw')",
        "button:has-text('Wystaw')",
    ],
    # Potwierdzenie sukcesu (nagłówek po redirect).
    "confirmation": [
        "[data-testid=confirmation-heading]",
        "h1:has-text('Ogłoszenie dodane')",
        ".success-message",
    ],
    # Wykrywanie captcha (dowolny znany marker).
    "captcha_marker": [
        "[data-testid=captcha]",
        "iframe[src*='recaptcha']",
        "//*[contains(translate(., 'CAPTCHA', 'captcha'), 'captcha')]",
    ],
}


# --- Exceptions ------------------------------------------------------------

class SelectorMissing(Exception):
    """Wszystkie fallback selektory dla klucza zawiodły."""

    def __init__(self, key: str, tried: list[str] | None = None) -> None:
        self.key = key
        self.tried = tried or []
        super().__init__(f"Selector missing: {key} (tried {len(self.tried)} fallbacks)")


# --- Public API ------------------------------------------------------------

async def resolve(page: Page, key: str, timeout: int = 5000) -> Locator:
    """Próbuje selektory w kolejności — zwraca pierwszy który się wyresolvuje.

    Args:
        page: Playwright ``Page``.
        key: klucz z ``SELECTORS``.
        timeout: total timeout per pojedyncza próba (ms).

    Returns:
        ``Locator`` (pierwszy match) — gotowy do click/fill.

    Raises:
        KeyError: gdy ``key`` nie istnieje w ``SELECTORS``.
        SelectorMissing: gdy wszystkie fallbacki fail (po ``timeout`` per próba).
    """
    if key not in SELECTORS:
        raise KeyError(f"Unknown selector key: {key}")

    candidates = SELECTORS[key]
    tried: list[str] = []

    for selector in candidates:
        tried.append(selector)
        try:
            locator = page.locator(selector).first
            # wait_for state=attached → element w DOM (nie musi być visible).
            await locator.wait_for(state="attached", timeout=timeout)
            return locator
        except Exception:
            continue

    # Wszystkie fail → log + raise.
    await log_selector_failure(page, key, tried)
    raise SelectorMissing(key, tried=tried)


async def log_selector_failure(page: Page, key: str, tried: list[str]) -> None:
    """Zapisuje JSONL entry do ``output/logs/selector_failures.log``.

    Zawiera: timestamp, key, tried selektory, URL, tytuł strony, HTML snippet
    (pierwsze 2000 znaków body).
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOGS_DIR / "selector_failures.log"

        try:
            html_snippet = await page.content()
            html_snippet = html_snippet[:2000]
            title = await page.title()
            url = page.url
        except Exception:
            html_snippet = "<snapshot unavailable>"
            title = ""
            url = ""

        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "key": key,
            "tried": tried,
            "url": url,
            "title": title,
            "html_snippet": html_snippet,
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Nigdy nie pozwól, żeby logging zabił flow.
        traceback.print_exc(file=sys.stdout)


def registry_keys() -> list[str]:
    """Zwraca posortowaną listę kluczy — dla testów/introspekcji."""
    return sorted(SELECTORS.keys())
