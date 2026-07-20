"""LIVE post test — REAL wystawienie oferty na konto OLX.

⚠️  UWAGA: to skrypt ODPALA REAL POST na twoim koncie. Oferta pojawi się
publicznie. Po teście usuń ręcznie w panelu OLX.

Kroki:
  1. Pobierz obrazek z URL do output/live_test_<ts>/image.jpg
  2. Uruchom patchright chromium (headless=True — mniej intruzywne)
  3. Login przez login_manager
  4. Screenshot 01_after_login
  5. Wystaw ofertę przez listing_creator (skip_pjs=True, bez packet buy)
  6. Screenshot 02_after_submit
  7. Log rezultatu (URL oferty jeśli sukces, error jeśli fail)

Env vars (wymagane):
    OLX_LIVE_EMAIL
    OLX_LIVE_PASSWORD
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import httpx

from patchright.async_api import async_playwright

# Dodaj app do sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.olx.listing_creator import (  # noqa: E402
    CaptchaDetected,
    ListingInput,
    create_listing,
)
from app.olx.login_manager import login  # noqa: E402


TITLE = "Dywan 150x100 Szary Villago"
DESC = (
    "Sprzedam ładny dywan Villago w rozmiarze 150x100 cm. Kolor szary, "
    "świetnie pasuje do salonu lub sypialni. Stan bardzo dobry, gotowy do wysyłki."
)
IMAGE_URL = "https://i.ibb.co/Zz8NL3gk/3807-SPEC.jpg"
PRICE = 50.0
CATEGORY_HINT = "dywan"
LOCATION_VARIANT = "Warszawa Śródmieście"
ACCOUNT_NAME = "sklepvillago"
SKU = "TEST-DYWAN-VILLAGO-150x100"


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _download_image(url: str, dest: Path) -> Path:
    _log(f"Pobieram obrazek: {url}")
    resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    data = resp.content
    dest.write_bytes(data)
    _log(f"  → {dest} ({len(data)} bytes)")
    return dest


async def main() -> int:
    email = os.getenv("OLX_LIVE_EMAIL")
    password = os.getenv("OLX_LIVE_PASSWORD")
    if not email or not password:
        _log("ERROR: brak OLX_LIVE_EMAIL / OLX_LIVE_PASSWORD w env")
        return 2

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(__file__).resolve().parent.parent / "output" / f"live_test_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)
    _log(f"Output dir: {output_dir}")

    # 1. Download image
    image_path = _download_image(IMAGE_URL, output_dir / "image.jpg")

    listing = ListingInput(
        product_sku=SKU,
        title=TITLE,
        description=DESC,
        price_pln=PRICE,
        city_label=LOCATION_VARIANT,
        location_variant=LOCATION_VARIANT,
        category_hint=CATEGORY_HINT,
        image_paths=[image_path],
        account_name=ACCOUNT_NAME,
        skip_pjs=True,  # skip packet buy modal
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        ctx = await browser.new_context(
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        # 2. Login
        _log("=== KROK 1: LOGIN ===")
        try:
            success = await login(page, email, password)
        except Exception as exc:
            _log(f"LOGIN EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            await page.screenshot(path=str(output_dir / "00_login_error.png"), full_page=True)
            await browser.close()
            return 3

        await page.screenshot(path=str(output_dir / "01_after_login.png"), full_page=True)
        _log(f"login result: {success}")
        _log(f"URL po loginie: {page.url}")
        if not success:
            _log("❌ LOGIN FAILED — sprawdź screenshot 01_after_login.png")
            await browser.close()
            return 4

        # 3. Create listing
        _log("=== KROK 2: CREATE LISTING ===")
        try:
            result = await create_listing(page, listing)
        except CaptchaDetected as exc:
            _log(f"❌ CAPTCHA: {exc}")
            await page.screenshot(path=str(output_dir / "02_captcha.png"), full_page=True)
            await browser.close()
            return 5
        except Exception as exc:
            _log(f"CREATE_LISTING EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            await page.screenshot(path=str(output_dir / "02_create_error.png"), full_page=True)
            await browser.close()
            return 6

        await page.screenshot(path=str(output_dir / "03_final.png"), full_page=True)

        _log("=== REZULTAT ===")
        _log(f"  success:     {result.success}")
        _log(f"  url:         {result.url}")
        _log(f"  screenshot:  {result.screenshot_path}")
        _log(f"  error:       {result.error}")
        _log(f"  metadata:    {result.metadata}")

        await browser.close()
        return 0 if result.success else 7


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
