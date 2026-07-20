"""Login manager — automated + dev (manual) login flows.

**Dev login (rekomendowane dla setup)**: user loguje się ręcznie w otwartym
headed browserze. Session zapisywana w ``user_data_dir`` (cookies, localStorage,
IndexedDB). Zero credentials w kodzie/env.

**Automated login**: fallback dla CI / non-interactive runs. Wymaga
``OLX_TEST_EMAIL`` + ``OLX_TEST_PASSWORD`` w env lub argumentów CLI. Używa
humanizera (variable typing + delays) żeby nie wyglądać na bota.

⚠️  TO_VERIFY: DOM login page OLX. Selektory oparte na typowych patternach —
user zwaliduje przez codegen. Update poprzez ``LOGIN_SELECTORS`` niżej.

CLI usage:
    python -m app.olx.login_manager dev_login test-account
    python -m app.olx.login_manager status test-account
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from typing import Any

from patchright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from .browser_pool import create_browser
from .humanizer import human_action_pause, human_type

__all__ = [
    "LOGIN_SELECTORS",
    "is_logged_in",
    "login",
    "dev_login",
]


#: URL-e OLX (TO_VERIFY: OLX bywa migruje do /account/login lub /konto/login).
OLX_LOGIN_URL: str = "https://www.olx.pl/mojolx"
OLX_ACCOUNT_URL: str = "https://www.olx.pl/mojolx"
OLX_HOME_URL: str = "https://www.olx.pl/"


#: TO_VERIFY: selektory formularza login OLX.
LOGIN_SELECTORS: dict[str, list[str]] = {
    "email_input": [
        "[data-testid=email-input]",
        "input[name=username]",
        "input[type=email]",
        "input[autocomplete=username]",
    ],
    "password_input": [
        "[data-testid=password-input]",
        "input[name=password]",
        "input[type=password]",
        "input[autocomplete=current-password]",
    ],
    "submit_button": [
        "[data-testid=login-submit]",
        "button[type=submit]",
        "button:has-text('Zaloguj')",
    ],
    # Marker "jestem zalogowany" — avatar w headerze lub link do mojolx.
    "logged_in_marker": [
        "[data-testid=header-user-avatar]",
        "a[href*='mojolx']",
        "a[href*='mojolx']",
        "[data-testid=user-menu]",
    ],
    # Cookie banner — zaakceptować przed loginem żeby nie zasłaniał inputów.
    "cookie_accept": [
        "[data-testid=cookie-accept]",
        "button:has-text('Akceptuję')",
        "button:has-text('Zaakceptuj')",
        "#onetrust-accept-btn-handler",
    ],
}


async def _try_selectors(page: Page, selectors: list[str], timeout: int = 3000) -> Any:
    """Zwraca pierwszy resolvowalny locator lub ``None`` gdy żaden nie działa."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="attached", timeout=timeout)
            return loc, sel
        except Exception:
            continue
    return None


async def _accept_cookies_if_present(page: Page) -> None:
    """Kliknij cookie banner jeśli obecny (best-effort, nie fail-hard)."""
    result = await _try_selectors(page, LOGIN_SELECTORS["cookie_accept"], timeout=2000)
    if result is None:
        return
    loc, _sel = result
    try:
        await loc.click(timeout=2000)
        await human_action_pause(0.4, 1.0)
    except Exception:  # pragma: no cover
        pass


async def is_logged_in(page: Page, passive: bool = False) -> bool:
    """Sprawdza czy sesja jest aktywna.

    OLX 2026-07 OAuth flow: ``/mojolx`` bez sesji → 302 do ``login.olx.pl/?...``
    (subdomena OAuth PKCE z code_challenge/state). Zalogowany → dashboard 200.

    Args:
        page: Playwright Page.
        passive: gdy True, TYLKO sprawdza aktualny URL + DOM markery, NIE
            wywołuje ``page.goto()``. Kluczowe dla ``dev_login`` który
            polluje w tle gdy user wypełnia login form — aktywna nawigacja
            nadpisała by wpisane hasło.

    Strategia:
        1. Szuka markera "logged_in" na obecnej stronie (avatar / user menu).
        2. Passive: sprawdź URL — jesteśmy w OAuth (``login.olx.pl``) →
           z pewnością nie zalogowany.
        3. Active (nie passive): fallback goto ``/mojolx`` → sprawdź hostname.

    Returns:
        True jeśli zalogowany.
    """
    # Passive check: jeśli już jesteśmy na OAuth login/callback URL, nie zalogowany.
    url_lower = page.url.lower()
    if "login.olx.pl" in url_lower or "/d/callback" in url_lower:
        return False

    # 1. Marker w bieżącym DOM (krótki timeout — dev_login nie może czekać).
    result = await _try_selectors(page, LOGIN_SELECTORS["logged_in_marker"], timeout=1500)
    if result is not None:
        return True

    if passive:
        # Dev_login mode: nie nawiguj, poll znowu za chwilę.
        return False

    # 2. Active fallback: sprawdź /mojolx (dla headless status check).
    try:
        await page.goto(OLX_ACCOUNT_URL, wait_until="domcontentloaded", timeout=15000)
    except PlaywrightTimeoutError:
        return False

    url_lower = page.url.lower()
    if "login.olx.pl" in url_lower or "/d/callback" in url_lower:
        return False

    result = await _try_selectors(page, LOGIN_SELECTORS["logged_in_marker"], timeout=3000)
    return result is not None


async def login(page: Page, email: str, password: str) -> bool:
    """Automated login flow z humanizacją.

    OLX 2026-07 używa OAuth PKCE na ``login.olx.pl`` subdomena. Playwright
    automatycznie follow'uje redirect z ``www.olx.pl/mojolx`` do login page.

    Kroki:
        1. Goto ``/mojolx`` → 302 do ``login.olx.pl/?cc=...&code_challenge=...``.
        2. Zaakceptuj cookies (jeśli banner).
        3. ``human_type`` na email → pauza → ``human_type`` na password.
        4. Pauza → submit → OAuth callback do ``www.olx.pl/d/callback/``.
        5. Wait for navigation → sprawdź ``is_logged_in()``.

    Args:
        page: Playwright Page (świeży).
        email: OLX login (email).
        password: hasło.

    Returns:
        True gdy login sukces, False gdy niepowodzenie (błędne credentials
        lub selektor nie pasuje).

    Raises:
        PlaywrightTimeoutError: gdy strona login się nie ładuje.
    """
    await page.goto(OLX_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    await human_action_pause(1.5, 3.5)
    await _accept_cookies_if_present(page)

    email_result = await _try_selectors(page, LOGIN_SELECTORS["email_input"], timeout=5000)
    if email_result is None:
        print("[login_manager] email_input selector nie znaleziony", flush=True)
        return False
    _, email_sel = email_result
    await human_type(page, email_sel, email)
    await human_action_pause(0.6, 1.4)

    pwd_result = await _try_selectors(page, LOGIN_SELECTORS["password_input"], timeout=5000)
    if pwd_result is None:
        print("[login_manager] password_input selector nie znaleziony", flush=True)
        return False
    _, pwd_sel = pwd_result
    await human_type(page, pwd_sel, password)
    await human_action_pause(0.8, 2.0)

    submit_result = await _try_selectors(page, LOGIN_SELECTORS["submit_button"], timeout=3000)
    if submit_result is None:
        print("[login_manager] submit_button selector nie znaleziony", flush=True)
        return False
    submit_loc, _ = submit_result
    try:
        async with page.expect_navigation(timeout=20000, wait_until="domcontentloaded"):
            await submit_loc.click()
    except PlaywrightTimeoutError:
        # Niektóre login flows nie robią navigation (SPA) — nadal sprawdź stan.
        pass

    await human_action_pause(1.0, 2.5)
    return await is_logged_in(page)


# --- Dev login (manual) ----------------------------------------------------

async def dev_login(
    account_name: str,
    timeout_s: int = 300,
) -> bool:
    """Otwiera headed browser — user loguje się RĘCZNIE, session zostaje w profilu.

    Ścieżka rekomendowana dla setup nowego konta:

    1. Uruchamiasz ``python -m app.olx.login_manager dev_login <name>``.
    2. Chromium się otwiera na stronie logowania OLX.
    3. Ręcznie: klikasz cookies, wpisujesz login/pass, ewentualnie MFA/CAPTCHA.
    4. Skrypt polluje ``is_logged_in()`` co 5s (max ``timeout_s``).
    5. Po sukcesie: session zapisana w ``user_data_dir`` (persistent).

    Args:
        account_name: nazwa konta (mapa na ``PROFILES_DIR/<name>``).
        timeout_s: max czas na manualny login (default 5 min).

    Returns:
        True jeśli wykryto login przed timeoutem.
    """
    context, page, playwright = await create_browser(
        account_name=account_name,
        headless=False,
    )
    try:
        # wait_until="commit" — zwraca natychmiast po pierwszym HTTP response
        # (nawet gdy potem lecą OAuth redirects). "domcontentloaded" na OLX 2026-07
        # timeoutuje 30s bo OAuth redirect chain nigdy nie firuje DOMContentLoaded
        # na finalnej stronie w czasie. "commit" pozwala user od razu widzieć browser.
        try:
            await page.goto(OLX_LOGIN_URL, wait_until="commit", timeout=60000)
        except PlaywrightTimeoutError:
            # Ostatnia deska ratunku — po prostu goto bez wait_until, browser
            # sam się załaduje w tle. User i tak może się logować.
            print(f"[dev_login] goto commit timeout — kontynuuję (browser sam załaduje)", flush=True)

        # Nie czekaj na cookies tutaj — może OAuth jeszcze się nie zakończył.
        # User sam kliknie cookies gdy zobaczy banner.
        print(
            f"[dev_login] Browser otwarty dla '{account_name}'.\n"
            f"           1. Poczekaj aż strona się załaduje (może chwilę).\n"
            f"           2. Zaakceptuj cookies jeśli banner.\n"
            f"           3. Wpisz email + hasło + kliknij Zaloguj.\n"
            f"           Czekam do {timeout_s}s.",
            flush=True,
        )

        elapsed = 0.0
        interval = 3.0
        while elapsed < timeout_s:
            await asyncio.sleep(interval)
            elapsed += interval
            try:
                # PASSIVE — NIE nawiguj żeby nie nadpisać login formu który
                # user aktualnie wypełnia.
                if await is_logged_in(page, passive=True):
                    print(f"[dev_login] SUCCESS — sesja zapisana w profile dir.", flush=True)
                    # Krótki settle żeby localStorage zdążył flushnąć.
                    await asyncio.sleep(3)
                    return True
            except Exception as e:
                # Nie print full traceback co 3s — tylko krótki komunikat.
                # Full traceback tylko dla niespodziewanych errorów.
                err_str = str(e)
                if "TargetClosedError" in err_str or "closed" in err_str.lower():
                    print(f"[dev_login] Browser zamknięty przez user — kończę.", flush=True)
                    return False
                # Inne błędy — kontynuuj polling, ale nie spam log.

        print(f"[dev_login] TIMEOUT po {timeout_s}s — login niewykryty.", flush=True)
        return False
    finally:
        try:
            await context.close()
        except Exception:  # pragma: no cover
            pass
        try:
            await playwright.stop()
        except Exception:  # pragma: no cover
            pass


async def status(account_name: str) -> bool:
    """Otwiera profile w headless i sprawdza czy sesja żyje. Print + return."""
    context, page, playwright = await create_browser(
        account_name=account_name,
        headless=True,
    )
    try:
        await page.goto(OLX_HOME_URL, wait_until="domcontentloaded", timeout=30000)
        ok = await is_logged_in(page)
        print(f"[status] account='{account_name}' logged_in={ok}", flush=True)
        return ok
    finally:
        await context.close()
        await playwright.stop()


# --- CLI -------------------------------------------------------------------

def _cli() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python -m app.olx.login_manager dev_login <account_name>\n"
            "  python -m app.olx.login_manager status <account_name>\n"
            "  python -m app.olx.login_manager auto_login <account_name>  # env OLX_TEST_EMAIL/PASSWORD",
            flush=True,
        )
        sys.exit(2)

    cmd = sys.argv[1]
    account = sys.argv[2]

    if cmd == "dev_login":
        ok = asyncio.run(dev_login(account))
        sys.exit(0 if ok else 1)
    elif cmd == "status":
        ok = asyncio.run(status(account))
        sys.exit(0 if ok else 1)
    elif cmd == "auto_login":
        email = os.getenv("OLX_TEST_EMAIL")
        password = os.getenv("OLX_TEST_PASSWORD")
        if not email or not password:
            print("[auto_login] OLX_TEST_EMAIL / OLX_TEST_PASSWORD brakuje w env.",
                  flush=True)
            sys.exit(2)

        async def _run() -> bool:
            context, page, playwright = await create_browser(
                account_name=account, headless=False
            )
            try:
                return await login(page, email, password)
            finally:
                await context.close()
                await playwright.stop()

        ok = asyncio.run(_run())
        sys.exit(0 if ok else 1)
    else:
        print(f"Unknown command: {cmd}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    _cli()
