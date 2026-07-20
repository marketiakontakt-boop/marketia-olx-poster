"""Diagnostyka dev_login — uruchamia browser, sprawdza state co 3s przez 30s."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.olx.browser_pool import create_browser
from app.olx.login_manager import OLX_LOGIN_URL, LOGIN_SELECTORS


async def diagnose(account: str = "debug-test"):
    print(f"[DIAG] Startuję browser dla '{account}'...", flush=True)
    context, page, playwright = await create_browser(
        account_name=account,
        headless=False,
    )
    print(f"[DIAG] Browser context created. page.url={page.url!r}", flush=True)

    try:
        print(f"[DIAG] Goto {OLX_LOGIN_URL} (wait_until=commit, timeout=60s)...", flush=True)
        try:
            await page.goto(OLX_LOGIN_URL, wait_until="commit", timeout=60000)
            print(f"[DIAG] Goto returned. page.url={page.url!r}", flush=True)
        except Exception as e:
            print(f"[DIAG] Goto exception: {type(e).__name__}: {e}", flush=True)

        # Poll state co 3s przez 30s
        for i in range(10):
            await asyncio.sleep(3)
            try:
                url = page.url
                title = await page.title()
                content_len = len(await page.content())
                # Check for OAuth login page indicators
                has_email = await page.locator("input[type=email]").count()
                has_password = await page.locator("input[type=password]").count()
                has_avatar = await page.locator("[data-testid=header-user-avatar]").count()
                print(
                    f"[DIAG t={3*(i+1)}s] url={url[:80]!r} title={title[:40]!r} "
                    f"content={content_len}B email={has_email} pwd={has_password} avatar={has_avatar}",
                    flush=True,
                )
            except Exception as e:
                print(f"[DIAG t={3*(i+1)}s] state check failed: {type(e).__name__}: {e}", flush=True)
                break

        # Screenshot na koniec dla wglądu
        screenshot_path = Path(__file__).parent.parent / "output" / "logs" / "diag_screenshot.png"
        try:
            await page.screenshot(path=str(screenshot_path), full_page=False)
            print(f"[DIAG] Screenshot: {screenshot_path}", flush=True)
        except Exception as e:
            print(f"[DIAG] Screenshot failed: {e}", flush=True)

    finally:
        print("[DIAG] Zamykam browser...", flush=True)
        try:
            await context.close()
        except Exception:
            pass
        try:
            await playwright.stop()
        except Exception:
            pass


if __name__ == "__main__":
    account = sys.argv[1] if len(sys.argv) > 1 else "debug-test"
    asyncio.run(diagnose(account))
