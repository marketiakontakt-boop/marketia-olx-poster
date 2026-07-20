"""Patchright browser pool z persistent context per konto.

**DECYZJA USER-A (2026-07-17):** BEZ PROXY. Kod NIE używa ``proxy=`` w launch —
``account_config.proxy`` pozostaje w JSON schema (SPEC sekcja 4) ale zawsze
``null``.

Każde konto ma własny ``user_data_dir`` (izolacja cookies + localStorage +
IndexedDB). Session persistence działa automatycznie dzięki
``launch_persistent_context()``.

TO_VERIFY: init script spoofów (plugins, languages, webdriver) — best-guess na
podstawie znanych fingerprint checks. Live OLX może wymagać dodatkowych
adjustmentów po testach użytkownika.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

from patchright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

# Patchright ma wbudowane anti-detect patches (runtime.enable, Console.enable,
# iframe fingerprints, itp.) — nie łączymy go z playwright-stealth (konflikt
# patchy per patchright docs).

from ..config import PROFILES_DIR

__all__ = [
    "create_browser",
    "BrowserPool",
    "STEALTH_INIT_SCRIPT",
]


# --- Init script -----------------------------------------------------------

#: JS wstrzykiwane przed każdym dokumentem. Pełny fingerprint spoofing dla
#: Chromium bundled przez Playwright (który normalnie wygląda jak "Chrome for
#: Testing" — natychmiast wykrywany).
#:
#: Coverage: webdriver, plugins, languages, chrome runtime, permissions,
#: WebGL vendor (Apple M-series), canvas noise, notification permission,
#: hardwareConcurrency, deviceMemory, connection type, screen resolution.
STEALTH_INIT_SCRIPT: str = r"""
(() => {
    // === 1. webdriver ===
    Object.defineProperty(navigator, 'webdriver', { get: () => false, configurable: true });
    delete Object.getPrototypeOf(navigator).webdriver;

    // === 2. languages ===
    Object.defineProperty(navigator, 'languages', {
        get: () => ['pl-PL', 'pl', 'en-US', 'en'],
        configurable: true,
    });

    // === 3. plugins ===
    const fakePlugins = [
        { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    ];
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            fakePlugins.item = (i) => fakePlugins[i];
            fakePlugins.namedItem = (n) => fakePlugins.find(p => p.name === n);
            fakePlugins.refresh = () => undefined;
            return fakePlugins;
        },
        configurable: true,
    });

    // === 4. chrome runtime object ===
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            OnInstalledReason: {},
            OnRestartRequiredReason: {},
            PlatformArch: {},
            PlatformNaclArch: {},
            PlatformOs: { MAC: 'mac' },
            RequestUpdateCheckStatus: {},
            connect: () => {},
            sendMessage: () => {},
        };
    }
    window.chrome.loadTimes = () => ({
        commitLoadTime: performance.now() / 1000,
        connectionInfo: 'h2',
        finishDocumentLoadTime: performance.now() / 1000,
        finishLoadTime: performance.now() / 1000,
        firstPaintAfterLoadTime: 0,
        firstPaintTime: performance.now() / 1000,
        navigationType: 'Other',
        npnNegotiatedProtocol: 'h2',
        requestTime: performance.now() / 1000,
        startLoadTime: performance.now() / 1000,
        wasAlternateProtocolAvailable: false,
        wasFetchedViaSpdy: true,
        wasNpnNegotiated: true,
    });
    window.chrome.csi = () => ({
        onloadT: Date.now(),
        pageT: performance.now(),
        startE: Date.now() - 100,
        tran: 15,
    });

    // === 5. Permissions.query workaround ===
    const oQ = window.navigator.permissions && window.navigator.permissions.query;
    if (oQ) {
        window.navigator.permissions.query = (p) => (
            p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : oQ.call(window.navigator.permissions, p)
        );
    }

    // === 6. WebGL vendor spoofing → Apple Silicon ===
    const getP = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Apple Inc.';        // UNMASKED_VENDOR_WEBGL
        if (param === 37446) return 'Apple M2';           // UNMASKED_RENDERER_WEBGL
        return getP.call(this, param);
    };
    if (window.WebGL2RenderingContext) {
        const getP2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return 'Apple Inc.';
            if (param === 37446) return 'Apple M2';
            return getP2.call(this, param);
        };
    }

    // === 7. Canvas fingerprint noise (add tiny per-session noise) ===
    const oToBlob = HTMLCanvasElement.prototype.toBlob;
    const oToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const oGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    const noise = Math.random() * 0.0001;
    HTMLCanvasElement.prototype.toDataURL = function(...args) {
        const ctx = this.getContext('2d');
        if (ctx) {
            ctx.fillStyle = 'rgba(0,0,0,' + noise + ')';
            ctx.fillRect(0, 0, 1, 1);
        }
        return oToDataURL.apply(this, args);
    };

    // === 8. Hardware / device signals ===
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true });
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0, configurable: true });
    Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel', configurable: true });

    // === 9. Notification permission ===
    if (window.Notification) {
        Object.defineProperty(Notification, 'permission', { get: () => 'default', configurable: true });
    }

    // === 10. Connection info (spoofuj 4g wifi jak zwykły desktop) ===
    if (navigator.connection) {
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false,
            }),
            configurable: true,
        });
    }

    // === 11. Ukryj console.debug używane przez detection ===
    // (headless zwykle nie ma console.debug używanego przez CDP)
})();
"""

#: Realistic User-Agent — Chrome 139 na macOS Sequoia (najnowszy stabilny).
#: Bez tego Playwright wysyła "HeadlessChrome" lub "Chrome for Testing" które są
#: natychmiast wykrywane przez anti-fraud.
REAL_USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.7258.128 Safari/537.36"
)


# --- Launch args -----------------------------------------------------------

_LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    # Ukryj sygnały automation w window.navigator
    "--exclude-switches=enable-automation",
    "--disable-background-networking",
    # Nie chcemy że OLX widzi "test" w UA
    "--disable-features=IsolateOrigins,site-per-process",
    # Prevent Chrome dev tools banner (kolejny sygnał)
    "--disable-features=UserAgentClientHint",
]

_IGNORE_DEFAULT_ARGS: list[str] = [
    "--enable-automation",
    "--enable-blink-features=IdleDetection",  # dodatkowy sygnał headless
]


def _cleanup_stale_singleton_locks(user_data_dir: Path) -> None:
    """Usuń stale Chromium Singleton locks (Cookie/Lock/Socket).

    Chromium używa tych plików aby zapobiec równoczesnemu użyciu tego samego
    profilu przez 2 instancje. Gdy poprzednia instancja padła bez sprzątania
    (crash, SIGKILL, timeout w Playwright driver), locks zostają i blokują
    kolejne uruchomienie → ``about:blank`` bez błędu.

    Sprawdzamy czy target linku (PID w symlinku) istnieje jako proces. Jeśli
    NIE → safe usunąć. Jeśli TAK → skip (żywa instancja).
    """
    import os
    for name in ("SingletonCookie", "SingletonLock", "SingletonSocket"):
        lock_path = user_data_dir / name
        if not lock_path.is_symlink() and not lock_path.exists():
            continue
        try:
            # SingletonCookie / SingletonSocket to symlinki z target = <hostname>-<pid>
            # albo random ID. Bezpiecznie: jeśli lock istnieje, sprawdź czy jakiś
            # Chromium proces działa z tym user_data_dir. Jeśli nie — usuń.
            has_running = _any_chromium_on_profile(str(user_data_dir))
            if has_running:
                print(
                    f"[browser_pool] LIVE Chromium używa {user_data_dir.name} — "
                    f"skip cleanup (lock={name})",
                    flush=True,
                )
                continue
            lock_path.unlink()
            print(f"[browser_pool] Cleaned stale lock: {name}", flush=True)
        except OSError as exc:
            print(f"[browser_pool] Cleanup {name} failed: {exc}", flush=True)


def _any_chromium_on_profile(profile_path: str) -> bool:
    """Zwraca True gdy jakiś proces Chromium ma ``--user-data-dir=<profile>``."""
    import subprocess
    try:
        out = subprocess.run(
            ["ps", "-Ao", "args="],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    marker = f"--user-data-dir={profile_path}"
    for line in out.splitlines():
        if marker in line and "Chrome" in line:
            return True
    return False


async def create_browser(
    account_name: str,
    user_data_dir: Path | None = None,
    headless: bool = False,
    playwright: Playwright | None = None,
) -> tuple[BrowserContext, Page, Playwright]:
    """Tworzy persistent Chromium context dla konta.

    Args:
        account_name: nazwa konta (używana do izolacji profile dir jeśli
            ``user_data_dir=None``).
        user_data_dir: opcjonalne override ścieżki profilu. Domyślnie
            ``PROFILES_DIR / account_name``.
        headless: ``False`` (default) dla dev-mode / manualnego logowania.
            ``True`` dla produkcyjnych runów.
        playwright: istniejąca instancja (dla reuse w BrowserPool). Gdy
            ``None`` — funkcja tworzy własny ``async_playwright().start()``.

    Returns:
        Tuple ``(context, page, playwright)``. Caller odpowiada za
        ``await context.close()`` + ``await playwright.stop()``.

    Notes:
        - Zero ``proxy=`` param (user decyzja 2026-07-17).
        - Viewport 1440x900 (typowy MacBook Air / desktop resolution).
        - Locale pl-PL + timezone Europe/Warsaw (spójne z targetem OLX).
        - Init script + patchright built-in patches przed jakimkolwiek ``goto()``.
    """
    user_data_dir = (user_data_dir or (PROFILES_DIR / account_name)).expanduser()
    user_data_dir.mkdir(parents=True, exist_ok=True)

    # Usuń zombie Chromium locks (SingletonCookie/Lock/Socket).
    # Bez tego nowy Chromium nie może otworzyć profile → about:blank.
    # Wcześniejsze uruchomienie mogło paść bez sprzątania (crash / kill -9).
    _cleanup_stale_singleton_locks(user_data_dir)

    own_playwright = playwright is None
    if playwright is None:
        playwright = await async_playwright().start()

    try:
        # Random viewport (drobne odchylenia od 1440x900 dla fingerprint variety).
        import random
        vw = random.choice([1440, 1512, 1680])
        vh = random.choice([900, 982, 1050])

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=headless,
            viewport={"width": vw, "height": vh},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent=REAL_USER_AGENT,  # zastąp "Chrome for Testing" prawdziwym UA
            color_scheme="light",
            device_scale_factor=2,  # macOS retina
            has_touch=False,
            is_mobile=False,
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
                "Sec-CH-UA": '"Chromium";v="139", "Not(A:Brand";v="8", "Google Chrome";v="139"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"macOS"',
            },
            args=_LAUNCH_ARGS,
            ignore_default_args=_IGNORE_DEFAULT_ARGS,
        )

        # Init script działa dla WSZYSTKICH przyszłych stron w context.
        await context.add_init_script(STEALTH_INIT_SCRIPT)

        # Pobierz lub utwórz pierwszą stronę.
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        return context, page, playwright
    except Exception:
        if own_playwright:
            await playwright.stop()
        raise


# --- Pool ------------------------------------------------------------------

class BrowserPool:
    """Zarządza contextami per konto — max 3 równolegle (Faza 4).

    Faza 2 obsługuje 1 konto testowe, ale klasa jest gotowa na scaling.
    Concurrency limit egzekwowany asymetrycznie: ``acquire()`` czeka gdy
    ``len(_active) >= max_concurrent``.
    """

    def __init__(self, max_concurrent: int = 3) -> None:
        self.max_concurrent = max_concurrent
        self._playwright: Playwright | None = None
        self._active: dict[str, tuple[BrowserContext, Page]] = {}

    async def start(self) -> None:
        """Startuje Playwright singleton (dzielony między konta)."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def stop(self) -> None:
        """Zamyka wszystkie contexty + Playwright. Bezpiecznie idempotent."""
        for name, (ctx, _page) in list(self._active.items()):
            try:
                await ctx.close()
            except Exception:  # pragma: no cover
                traceback.print_exc(file=sys.stdout)
            self._active.pop(name, None)

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # pragma: no cover
                traceback.print_exc(file=sys.stdout)
            self._playwright = None

    async def acquire(
        self,
        account_name: str,
        user_data_dir: Path | None = None,
        headless: bool = False,
    ) -> tuple[BrowserContext, Page]:
        """Zwraca (context, page) dla konta. Reużywa istniejący jeśli otwarty.

        Rzuca ``RuntimeError`` gdy pool już zawiera ``max_concurrent`` aktywnych
        contextów a ``account_name`` nowe.
        """
        if account_name in self._active:
            return self._active[account_name]

        if len(self._active) >= self.max_concurrent:
            raise RuntimeError(
                f"BrowserPool full ({self.max_concurrent} active). "
                f"Release existing before acquiring new account: {account_name}."
            )

        await self.start()
        assert self._playwright is not None
        context, page, _ = await create_browser(
            account_name=account_name,
            user_data_dir=user_data_dir,
            headless=headless,
            playwright=self._playwright,
        )
        self._active[account_name] = (context, page)
        return context, page

    async def release(self, account_name: str) -> None:
        """Zamyka pojedynczy context (np. koniec batcha dla konta)."""
        entry = self._active.pop(account_name, None)
        if entry is None:
            return
        ctx, _page = entry
        try:
            await ctx.close()
        except Exception:  # pragma: no cover
            traceback.print_exc(file=sys.stdout)

    async def __aenter__(self) -> "BrowserPool":
        await self.start()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.stop()
