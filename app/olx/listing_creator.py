"""Listing creator — pełny flow wystawiania ogłoszenia na OLX.

SPEC sekcja 9. Konsumuje:

- ``browser_pool`` (context + page przez wyższą warstwę).
- ``humanizer`` (typing/click/pauses).
- ``selector_registry`` (resolve z 3-level fallback).
- ``pjs_selector.ensure_pjs_active`` (KRITYCZNIE przed submitem).
- ``shared_db.save_listing`` (streaming save NATYCHMIAST po sukcesie).

Retry policy dla ``PlaywrightTimeoutError``: max 2 próby z fresh page reload
(learning z LEARNINGS_GLOBAL).

⚠️  TO_VERIFY: DOM /dodaj/ page, autocomplete category/location, kolejność
kroków. User walidacja przez codegen wymagana przed prod.
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from ..config import SCREENSHOTS_DIR
from ..data import shared_db
from .humanizer import human_action_pause, human_click, human_type
from .pjs_selector import PJSUnavailable, ensure_pjs_active
from .selector_registry import SELECTORS, SelectorMissing, resolve

__all__ = [
    "ListingInput",
    "ListingResult",
    "CaptchaDetected",
    "create_listing",
]


OLX_ADD_URL: str = "https://www.olx.pl/dodaj/"

#: Max retries dla transient PlaywrightTimeoutError (SPEC + learning).
MAX_RETRIES: int = 2


# --- Exceptions ------------------------------------------------------------

class CaptchaDetected(Exception):
    """OLX pokazał CAPTCHA — wyższa warstwa musi pauzować konto."""


# --- Data classes ----------------------------------------------------------

@dataclass(slots=True)
class ListingInput:
    """Wejściowe dane dla pojedynczego wystawienia."""

    product_sku: str
    title: str
    description: str
    price_pln: float
    city_label: str
    location_variant: str  # dokładny wpis do autocomplete
    category_hint: str  # nazwa lub fragment nazwy kategorii do wyszukania
    image_paths: list[Path]
    account_name: str
    #: Gdy True — wystaw nawet jeśli kategoria nie ma PJS ("Zapłać jeśli sprzedasz").
    #: Domyślnie False — brak PJS = job pauzowany z prośbą o decyzję usera.
    skip_pjs: bool = False


@dataclass(slots=True)
class ListingResult:
    """Rezultat wystawienia — używany przez wyższą warstwę (queue worker)."""

    success: bool
    url: str | None = None
    screenshot_path: Path | None = None
    error: str | None = None
    audit_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Detection helpers -----------------------------------------------------

async def _detect_captcha(page: Page) -> bool:
    """Wykrywa CAPTCHA na stronie (wszelkie znane markery)."""
    try:
        for sel in SELECTORS["captcha_marker"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    return True
            except Exception:
                continue
        # Fallback: text search
        content = await page.content()
        low = content.lower()
        if "recaptcha" in low or "hcaptcha" in low or "cf-challenge" in low:
            return True
    except Exception:
        pass
    return False


async def _take_screenshot(page: Page, account: str, sku: str, city: str) -> Path:
    """Zapisuje full_page screenshot pod ``output/screenshots/<account>/<YYYY-MM-DD>/``.

    Ścieżka: ``{account}/{date}/{sku}_{city}.png``. Sanitizuje city (spacje→_).
    """
    today = date.today().isoformat()
    dir_path = SCREENSHOTS_DIR / account / today
    dir_path.mkdir(parents=True, exist_ok=True)
    safe_city = city.replace("/", "_").replace(" ", "_")
    screenshot_path = dir_path / f"{sku}_{safe_city}.png"
    try:
        await page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        traceback.print_exc(file=sys.stdout)
    return screenshot_path


# --- Form step helpers -----------------------------------------------------

async def _select_category(page: Page, category_hint: str) -> None:
    """Klika category selector i wpisuje ``category_hint``.

    OLX autocomplete: klik → dropdown otwarty → wpisz kilka znaków →
    wybierz pierwszy wynik (Enter lub click).

    TO_VERIFY: kolejność interakcji (click vs. focus + type).
    """
    cat_loc = await resolve(page, "category_selector", timeout=8000)
    await cat_loc.scroll_into_view_if_needed()
    await human_click(page, SELECTORS["category_selector"][0])
    await human_action_pause(0.6, 1.4)
    # Wpisujemy hint przez keyboard (dropdown może nie mieć osobnego input).
    await page.keyboard.type(category_hint, delay=90)
    await human_action_pause(1.0, 2.0)
    # Wybór pierwszej sugestii — Enter (bezpieczniejsze niż click w listę).
    await page.keyboard.press("Enter")
    await human_action_pause(0.5, 1.2)


async def _fill_location(page: Page, location_variant: str) -> None:
    """Wpisz lokalizację i wybierz pierwszą sugestię z autocomplete."""
    loc_sel = SELECTORS["location_input"][0]
    # Resolve zapewnia że pole jest w DOM przed typem.
    await resolve(page, "location_input", timeout=8000)
    await human_type(page, loc_sel, location_variant)
    await human_action_pause(0.8, 1.6)
    # Autocomplete → wybór ArrowDown + Enter.
    await page.keyboard.press("ArrowDown")
    await human_action_pause(0.2, 0.5)
    await page.keyboard.press("Enter")
    await human_action_pause(0.4, 1.0)


async def _upload_photos(page: Page, image_paths: list[Path]) -> None:
    """Upload przez ``set_input_files`` na ``input[type=file]``.

    TODO v2: symulacja drag-drop (bardziej ludzka, ale wymaga CDP).
    """
    if not image_paths:
        return
    upload_loc = await resolve(page, "photo_upload", timeout=8000)
    files = [str(p) for p in image_paths if p.exists()]
    if not files:
        print(f"[listing_creator] BRAK plików do uploadu: {image_paths}", flush=True)
        return
    # set_input_files działa nawet gdy input jest hidden.
    await upload_loc.set_input_files(files)
    # OLX potrzebuje sekund na przetworzenie thumbnails.
    await human_action_pause(2.5, 5.0)


async def _fill_form(page: Page, listing: ListingInput) -> None:
    """Wypełnia całą formatkę w kolejności semantycznej.

    Kolejność MA znaczenie na OLX: category musi być pierwsza (odblokowuje
    dodatkowe pola).
    """
    # 1. Category
    await _select_category(page, listing.category_hint)

    # 2. Title
    await resolve(page, "title_input", timeout=8000)
    await human_type(page, SELECTORS["title_input"][0], listing.title)
    await human_action_pause(0.5, 1.3)

    # 3. Description
    await resolve(page, "description_input", timeout=8000)
    await human_type(page, SELECTORS["description_input"][0], listing.description)
    await human_action_pause(0.8, 1.8)

    # 4. Photos
    await _upload_photos(page, listing.image_paths)

    # 5. Location
    await _fill_location(page, listing.location_variant)

    # 6. Price
    await resolve(page, "price_input", timeout=8000)
    # Cena jako string bez separatorów tysięcy (OLX zjada `.` jako decimal).
    price_str = f"{listing.price_pln:.2f}".rstrip("0").rstrip(".")
    if not price_str:
        price_str = "0"
    await human_type(page, SELECTORS["price_input"][0], price_str)
    await human_action_pause(0.4, 1.0)

    # 7. Stan: nowe
    try:
        await resolve(page, "condition_new", timeout=5000)
        await human_click(page, SELECTORS["condition_new"][0])
        await human_action_pause(0.3, 0.9)
    except SelectorMissing:
        # Niektóre kategorie nie mają "stan" — nie fatal.
        print("[listing_creator] condition_new nieobecny — pomijam", flush=True)


async def _extract_listing_url(page: Page) -> str | None:
    """Po sukcesie: URL nowego ogłoszenia.

    Priorytet:
        1. ``window.location.href`` gdy zawiera ``/oferta/``.
        2. Link "Zobacz ogłoszenie" (data-testid).
        3. ``None`` gdy nie da się wyekstrahować.
    """
    try:
        current = page.url
        if "/oferta/" in current or "/d/oferta/" in current:
            return current

        for sel in (
            "[data-testid=view-listing-link]",
            "a:has-text('Zobacz ogłoszenie')",
            "a[href*='/oferta/']",
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    href = await loc.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            href = "https://www.olx.pl" + href
                        return href
            except Exception:
                continue
    except Exception:
        traceback.print_exc(file=sys.stdout)
    return None


# --- Main flow -------------------------------------------------------------

async def _create_listing_once(page: Page, listing: ListingInput) -> ListingResult:
    """Pojedyncza próba (bez retry). Zwraca ListingResult."""
    # 1. Nawigacja.
    await page.goto(OLX_ADD_URL, wait_until="networkidle", timeout=45000)
    await human_action_pause(2.0, 5.0)

    # 2. CAPTCHA check PRZED wypełnianiem.
    if await _detect_captcha(page):
        raise CaptchaDetected("CAPTCHA wykryte na stronie /dodaj/ przed formularzem.")

    # 3. Wypełnienie formularza.
    await _fill_form(page, listing)

    # 4. PJS — biznesowo krytyczne (chyba że user zdecydował skip).
    try:
        await ensure_pjs_active(page)
        pjs_status = "active"
    except PJSUnavailable as exc:
        pjs_status = "unavailable"
        if not listing.skip_pjs:
            # Job pauzowany — wyższa warstwa obsłuży modal dla usera.
            print(f"[listing_creator] PJS unavailable — awaiting user decision: {exc}", flush=True)
            return ListingResult(
                success=False,
                error="pjs_unavailable",
                metadata={
                    "stage": "pjs",
                    "category_hint": listing.category_hint,
                    "message": str(exc),
                },
            )
        # skip_pjs=True → kontynuuj bez PJS (świadoma decyzja).
        print(f"[listing_creator] PJS unavailable ale user zdecydował skip: {exc}", flush=True)

    # 5. Screenshot PRE-SUBMIT (audit trail).
    pre_submit_shot = await _take_screenshot(
        page, listing.account_name, listing.product_sku, listing.city_label + "_pre"
    )

    # 6. Submit.
    await resolve(page, "submit_button", timeout=8000)
    await human_action_pause(1.0, 2.5)
    await human_click(page, SELECTORS["submit_button"][0])

    # 7. Wait for confirmation.
    try:
        await resolve(page, "confirmation", timeout=30000)
    except SelectorMissing:
        # Może być captcha po submit.
        if await _detect_captcha(page):
            raise CaptchaDetected("CAPTCHA po submit.")
        raise

    # 8. Extract URL + screenshot final.
    await human_action_pause(1.5, 3.0)
    url = await _extract_listing_url(page)
    screenshot_path = await _take_screenshot(
        page, listing.account_name, listing.product_sku, listing.city_label
    )

    # 9. STREAMING SAVE — natychmiast po sukcesie (learning: nigdy po batchu).
    try:
        audit_id = shared_db.save_listing(
            sku=listing.product_sku,
            account_name=listing.account_name,
            city=listing.city_label,
            url=url,
            screenshot_path=str(screenshot_path),
            status="active",
        )
    except Exception as exc:
        # Nie fatal — mamy screenshot + URL. Loguj, ale zwróć sukces.
        traceback.print_exc(file=sys.stdout)
        print(f"[listing_creator] save_listing failed: {exc}", flush=True)
        audit_id = None

    print(
        f"[listing_creator] SUCCESS sku={listing.product_sku} "
        f"account={listing.account_name} city={listing.city_label} url={url}",
        flush=True,
    )
    return ListingResult(
        success=True,
        url=url,
        screenshot_path=screenshot_path,
        audit_id=audit_id,
        metadata={
            "pre_submit_screenshot": str(pre_submit_shot),
            "completed_at": datetime.utcnow().isoformat() + "Z",
        },
    )


async def create_listing(page: Page, listing: ListingInput) -> ListingResult:
    """Publiczna funkcja — pełny flow z retry policy.

    Retry:
        - ``PlaywrightTimeoutError`` → max ``MAX_RETRIES`` prób, każda z
          fresh ``goto()``.
        - ``CaptchaDetected`` → NIE retry (propagate up, wyższa warstwa
          pauzuje konto).
        - ``SelectorMissing`` → log + return ListingResult(error='selector_missing').
        - inne ``Exception`` → log + return ListingResult(error=str(e)).

    Args:
        page: gotowa Playwright Page (zalogowana).
        listing: dane do wystawienia.

    Returns:
        ListingResult (success True/False + metadata).

    Raises:
        CaptchaDetected: propaguje do wyższej warstwy (worker musi pauzować konto).
    """
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 2):  # 1 initial + MAX_RETRIES
        try:
            return await _create_listing_once(page, listing)
        except CaptchaDetected:
            # Nigdy nie retryuj CAPTCHA — propaguj.
            raise
        except SelectorMissing as exc:
            print(
                f"[listing_creator] SelectorMissing (attempt {attempt}): {exc}",
                flush=True,
            )
            traceback.print_exc(file=sys.stdout)
            # Screenshot dla debugu.
            try:
                await _take_screenshot(
                    page,
                    listing.account_name,
                    listing.product_sku,
                    listing.city_label + "_selector_fail",
                )
            except Exception:
                pass
            return ListingResult(
                success=False,
                error=f"selector_missing:{exc.key}",
                metadata={"attempts": attempt, "key": exc.key},
            )
        except PlaywrightTimeoutError as exc:
            last_err = exc
            print(
                f"[listing_creator] PlaywrightTimeoutError attempt {attempt}/{MAX_RETRIES + 1}: {exc}",
                flush=True,
            )
            traceback.print_exc(file=sys.stdout)
            if attempt > MAX_RETRIES:
                break
            # Fresh reload przed kolejną próbą.
            try:
                await page.reload(wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            await human_action_pause(3.0, 6.0)
        except Exception as exc:
            last_err = exc
            print(f"[listing_creator] Unexpected error: {exc}", flush=True)
            traceback.print_exc(file=sys.stdout)
            return ListingResult(
                success=False,
                error=str(exc),
                metadata={"exception_type": type(exc).__name__, "attempts": attempt},
            )

    # Wyczerpaliśmy retries dla timeout.
    return ListingResult(
        success=False,
        error=f"timeout_after_{MAX_RETRIES + 1}_attempts: {last_err}",
        metadata={"exception_type": "PlaywrightTimeoutError"},
    )
