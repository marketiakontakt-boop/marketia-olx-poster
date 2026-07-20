"""Ban detector — mock-based, nie wymaga live OLX.

Weryfikuje ``check_http_signals`` i ``check_dom_signals`` na sztucznych obiektach
Response/Page. Suite szybka (<1s), można ją zawsze uruchomić w CI.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.monitor.ban_detector import (
    BAN_ACTIONS,
    check_dom_signals,
    check_http_signals,
)


@pytest.mark.asyncio
async def test_http_403_triggers_ban_action():
    mock_response = MagicMock(status=403, url="https://www.olx.pl/moje-konto/")
    reason = await check_http_signals(mock_response)
    assert reason == "http_403"


@pytest.mark.asyncio
async def test_http_429_rate_limit():
    mock_response = MagicMock(status=429, url="https://www.olx.pl/nowy/")
    reason = await check_http_signals(mock_response)
    assert reason == "http_429_rate_limit"


@pytest.mark.asyncio
async def test_http_5xx_transient():
    mock_response = MagicMock(status=502, url="https://www.olx.pl/nowy/")
    reason = await check_http_signals(mock_response)
    assert reason == "http_5xx_502"


@pytest.mark.asyncio
async def test_redirect_to_login():
    mock_response = MagicMock(
        status=200, url="https://www.olx.pl/zaloguj?redirect=/nowy/"
    )
    reason = await check_http_signals(mock_response)
    assert reason == "redirect_to_login"


@pytest.mark.asyncio
async def test_http_none_response():
    # None (np. offline) nie powinno fabrykować bana.
    reason = await check_http_signals(None)
    assert reason is None


@pytest.mark.asyncio
async def test_captcha_dom_detection():
    mock_page = MagicMock()
    # Locator .count() musi być awaitowalne i zwrócić >0
    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    mock_page.locator = MagicMock(return_value=locator)
    mock_page.content = AsyncMock(return_value="<html>OK</html>")

    reason = await check_dom_signals(mock_page)
    assert reason == "captcha_detected"


@pytest.mark.asyncio
async def test_ban_keyword_polish():
    mock_page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)  # brak CAPTCHA
    mock_page.locator = MagicMock(return_value=locator)
    mock_page.content = AsyncMock(
        return_value="""
        <html><body>
        <h1>Konto zostało zablokowane z powodu podejrzanej aktywności.</h1>
        </body></html>
        """
    )

    reason = await check_dom_signals(mock_page)
    assert reason and reason.startswith("ban_keyword")


@pytest.mark.asyncio
async def test_ban_keyword_english():
    mock_page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    mock_page.locator = MagicMock(return_value=locator)
    mock_page.content = AsyncMock(
        return_value="<html><body>Your account has been blocked.</body></html>"
    )
    reason = await check_dom_signals(mock_page)
    assert reason and reason.startswith("ban_keyword")


@pytest.mark.asyncio
async def test_rate_limit_keyword():
    mock_page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    mock_page.locator = MagicMock(return_value=locator)
    mock_page.content = AsyncMock(
        return_value="<html><body>Zbyt wiele prób — spróbuj ponownie później.</body></html>"
    )
    reason = await check_dom_signals(mock_page)
    assert reason and reason.startswith("rate_limit_keyword")


@pytest.mark.asyncio
async def test_dom_clean_page():
    mock_page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    mock_page.locator = MagicMock(return_value=locator)
    mock_page.content = AsyncMock(
        return_value="<html><body><h1>Twoje ogłoszenia</h1></body></html>"
    )
    reason = await check_dom_signals(mock_page)
    assert reason is None


def test_cascade_pause_action_captcha():
    """CAPTCHA → cascade 4h, urgent notification, kill_switch_prompt."""
    action = BAN_ACTIONS["captcha_detected"]
    assert action["cascade_pause_others_hours"] == 4
    assert action["notification"] == "urgent"
    assert action["kill_switch_prompt"] is True
    # pause_hours=None → infinite (dopóki user nie rozwiąże).
    assert action["pause_account_hours"] is None


def test_cascade_pause_action_ban_keyword():
    """Ban keyword → 7 dni pauza konta + 12h cascade."""
    action = BAN_ACTIONS["ban_keyword"]
    assert action["pause_account_hours"] == 24 * 7
    assert action["cascade_pause_others_hours"] == 12
    assert action["notification"] == "urgent"


def test_cascade_pause_action_http_5xx_transient():
    """5xx → brak pauzy, retry z backoffem (transient)."""
    action = BAN_ACTIONS["http_5xx"]
    assert action["pause_account_hours"] == 0
    assert action["cascade_pause_others_hours"] == 0
    assert action.get("retry_with_backoff") is True
