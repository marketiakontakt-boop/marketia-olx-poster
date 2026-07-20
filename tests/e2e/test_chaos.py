"""Chaos tests — network drop, browser crash, OLX 5xx.

Wymagają live browser + test account. Bez env vars ``OLX_TEST_EMAIL``/
``OLX_TEST_PASSWORD`` cała ścieżka jest **skipowana**.

Sprawdzają że graceful degradation działa: zamiast NoneType exception albo
zawieszki, kod zwraca ``result.success=False`` z sensownym error message.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.asyncio


def _skip_missing_prereqs() -> None:
    if not os.getenv("OLX_TEST_EMAIL") or not os.getenv("OLX_TEST_PASSWORD"):
        pytest.skip("E2E chaos requires OLX_TEST_EMAIL and OLX_TEST_PASSWORD")
    if not Path("/tmp/test-image.jpg").exists():
        pytest.skip("Brak /tmp/test-image.jpg")


def _make_listing(sku: str, title: str):
    from app.olx.listing_creator import ListingInput

    return ListingInput(
        product_sku=sku,
        title=title,
        description="chaos test — nie kupować",
        price_pln=1,
        city_label="Warszawa",
        location_variant="Warszawa",
        category_hint="AGD Drobne",
        image_paths=["/tmp/test-image.jpg"],
        account_name="test-account",
    )


async def test_network_drop_mid_listing(test_browser, clean_db):
    """Set offline BEFORE listing → oczekujemy timeout/network error."""
    _skip_missing_prereqs()

    try:
        from app.olx.listing_creator import create_listing
    except ImportError as exc:
        pytest.skip(f"listing_creator niedostępny: {exc}")

    await test_browser.context.set_offline(True)
    try:
        result = await create_listing(
            test_browser, _make_listing("CHAOS_001", "Chaos network")
        )
    finally:
        await test_browser.context.set_offline(False)

    assert not result.success
    err_lower = (result.error or "").lower()
    assert any(k in err_lower for k in ("timeout", "network", "offline", "err_", "net::"))


async def test_browser_crash_recovery(test_browser, clean_db):
    """Zamknij page mid-flight — kod powinien graceful fail (bez hangu)."""
    _skip_missing_prereqs()

    try:
        from app.olx.listing_creator import create_listing
    except ImportError as exc:
        pytest.skip(f"listing_creator niedostępny: {exc}")

    async def close_after_delay():
        await asyncio.sleep(2)
        try:
            await test_browser.close()
        except Exception:
            pass

    asyncio.create_task(close_after_delay())

    try:
        result = await asyncio.wait_for(
            create_listing(test_browser, _make_listing("CRASH_001", "Chaos crash")),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        pytest.fail("create_listing zawiesił się po browser.close (brak graceful fail)")

    assert not result.success, "listing nie powinno succeed po browser.close"
