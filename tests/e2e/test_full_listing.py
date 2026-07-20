"""E2E test pełnego flow wystawienia jednego ogłoszenia.

Wymaga live OLX test account. Bez env vars ``OLX_TEST_EMAIL``/``OLX_TEST_PASSWORD``
cała ścieżka jest **skipowana** (nie failuje).

Cena testowego ogłoszenia = 1 PLN, tytuł zawiera "TEST — nie kupować" żeby
nikt nie zakupił. Ręczne posprzątanie po teście: user usuwa ogłoszenie z panelu
OLX (nie robimy auto-delete żeby móc zweryfikować manualnie).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.asyncio


def _skip_missing_prereqs() -> None:
    if not os.getenv("OLX_TEST_EMAIL") or not os.getenv("OLX_TEST_PASSWORD"):
        pytest.skip("E2E requires OLX_TEST_EMAIL and OLX_TEST_PASSWORD env vars")
    test_image = Path("/tmp/test-image.jpg")
    if not test_image.exists():
        pytest.skip(
            "Brak /tmp/test-image.jpg — utwórz: convert -size 800x600 xc:red /tmp/test-image.jpg"
        )


async def test_full_listing_success(test_browser, clean_db):
    """Wystawia 1 ogłoszenie testowe, weryfikuje URL + DB + screenshot."""
    _skip_missing_prereqs()

    try:
        from app.olx.listing_creator import ListingInput, create_listing
        from app.data.shared_db import get_connection
    except ImportError as exc:
        pytest.skip(f"listing_creator/shared_db niedostępny: {exc}")

    listing = ListingInput(
        product_sku="TEST_E2E_001",
        title="TEST — Prosta lampa biurkowa 40cm — nie kupować",
        description=(
            "To jest ogłoszenie testowe stworzone automatycznie przez Marketia OLX "
            "Poster w ramach E2E testów. Proszę nie kupować."
        ),
        price_pln=1,
        city_label="Warszawa",
        location_variant="Warszawa, Śródmieście",
        category_hint="AGD Drobne",
        image_paths=["/tmp/test-image.jpg"],
        account_name="test-account",
    )

    result = await create_listing(test_browser, listing)

    assert result.success, f"Listing failed: {getattr(result, 'error', None)}"
    assert result.url and "olx.pl" in result.url
    assert result.screenshot_path and Path(result.screenshot_path).exists()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM olx_listings WHERE sku = ?", ("TEST_E2E_001",)
        ).fetchone()
    assert row is not None, "brak wpisu w olx_listings po sukcesie"
    assert row["url"] == result.url
    assert row["city"] == "Warszawa"
