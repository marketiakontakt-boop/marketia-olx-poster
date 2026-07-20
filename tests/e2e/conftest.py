"""E2E fixtures — wymaga env vars ``OLX_TEST_EMAIL`` / ``OLX_TEST_PASSWORD``.

Bez tych zmiennych testy z ``test_browser`` są **skipowane** (nie failują), więc
suite można uruchomić lokalnie bez konta OLX.

Fixture ``clean_db`` czyści tabele przed testem — nie wymaga env vars, używana
przez testy mock-based.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    import pytest_asyncio  # type: ignore[import-not-found]
    _HAVE_ASYNCIO = True
except ImportError:  # pragma: no cover
    pytest_asyncio = None  # type: ignore[assignment]
    _HAVE_ASYNCIO = False


def _skip_if_no_test_account() -> None:
    if not os.getenv("OLX_TEST_EMAIL") or not os.getenv("OLX_TEST_PASSWORD"):
        pytest.skip("E2E requires OLX_TEST_EMAIL and OLX_TEST_PASSWORD env vars")


if _HAVE_ASYNCIO:

    @pytest_asyncio.fixture(scope="session")
    async def test_browser():  # type: ignore[misc]
        """Session-level Playwright page zalogowany do test account.

        Skipuje jeśli brak env vars albo Playwright/browser_pool nie działają.
        """
        _skip_if_no_test_account()
        try:
            from app.olx.browser_pool import BrowserPool
        except ImportError as exc:
            pytest.skip(f"browser_pool niedostępny: {exc}")

        profile_dir = Path("/tmp/marketia-olx-e2e-profile")
        profile_dir.mkdir(parents=True, exist_ok=True)

        pool = BrowserPool()
        try:
            context, page = await pool.get_or_create(  # type: ignore[attr-defined]
                "test-account",
                user_data_dir=profile_dir,
                headless=True,
            )
        except Exception as exc:
            pytest.skip(f"nie mogę uruchomić przeglądarki: {exc}")

        try:
            yield page
        finally:
            try:
                await context.close()
            except Exception:
                pass


@pytest.fixture
def clean_db():
    """Cleanup DB tabel przed testem. Nie wymaga OLX creds — safe locally.

    Skipuje test gdy shared_db niedostępny (np. brak parent dir dla DB).
    """
    try:
        from app.data.shared_db import get_connection, run_migrations
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"shared_db niedostępny: {exc}")

    try:
        run_migrations()
    except Exception as exc:
        pytest.skip(f"nie mogę uruchomić migracji: {exc}")

    with get_connection() as conn:
        for stmt in (
            "DELETE FROM olx_jobs",
            "DELETE FROM olx_listings WHERE account_name = 'test-account'",
            "DELETE FROM variant_cache",
            "DELETE FROM olx_accounts_meta",
        ):
            try:
                conn.execute(stmt)
            except Exception:
                # Tabela może nie istnieć w wersji schemy — ignoruj.
                pass
    yield
    # Post-cleanup pomijamy — pozwól inspekcji po nieudanym teście.
