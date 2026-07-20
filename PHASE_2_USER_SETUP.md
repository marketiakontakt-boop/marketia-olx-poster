# Faza 2 — user setup (OLX integration)

Kroki które **użytkownik** wykonuje po zbudowaniu modułów Fazy 2 przez agenta.
Zero automatyzacji — te punkty wymagają decyzji lub ręcznego dostępu do OLX.

## 1. Playwright chromium

```bash
cd ~/Projects/marketia-olx-poster
source venv/bin/activate
playwright install chromium
```

Instaluje bundle chromium (~200 MB) do `~/Library/Caches/ms-playwright/`.

## 2. Profil dla konta testowego

```bash
mkdir -p data/profiles/test-account
```

Każde konto ma osobny profile dir (izolacja cookies/localStorage/IndexedDB).
Nazwa katalogu = `account_name` używany w `create_browser(account_name=...)`.

## 3. Dev login (rekomendowana ścieżka)

Bezpieczne: zero credentials w kodzie/env, użytkownik loguje się ręcznie
w otwartym headed browserze.

```bash
python -m app.olx.login_manager dev_login test-account
```

Kroki:

1. Skrypt otwiera Chromium na `https://www.olx.pl/konto/logowanie`.
2. Klikasz cookie banner, wpisujesz email + hasło, ewentualnie MFA/CAPTCHA.
3. Skrypt polluje `is_logged_in(page)` co 5s (timeout 300s).
4. Po sukcesie session zapisana w `data/profiles/test-account/` (persistent).
5. Print `[dev_login] SUCCESS` + exit 0.

Weryfikacja stanu w dowolnym momencie:

```bash
python -m app.olx.login_manager status test-account
```

## 4. Auto login (fallback dla CI / non-interactive)

Ustawiasz env vars i wywołujesz `auto_login`:

```bash
export OLX_TEST_EMAIL='marketia.kontakt@gmail.com'
export OLX_TEST_PASSWORD='***'
python -m app.olx.login_manager auto_login test-account
```

Kod używa `humanizer.human_type` — bezpieczniejsze niż `page.fill()`.
NIE zapisuj tych vars w `.env` commitowanym do git.

## 5. Walidacja selektorów (KRYTYCZNE przed prod)

Wszystkie selektory w `app/olx/selector_registry.py` i
`app/olx/login_manager.py` są **best-guess** — agent nie miał dostępu do live
OLX.

```bash
playwright codegen https://www.olx.pl/dodaj/
```

Kroki:

1. Playwright otwiera browser + inspektor.
2. Klikasz przez pełny flow ogłoszenia (kategoria → tytuł → opis → foto →
   lokalizacja → cena → stan → PJS → submit).
3. Inspektor generuje selektory w Pythonie.
4. Porównujesz z `SELECTORS` w `selector_registry.py`:
   - Jeśli identyczne → OK.
   - Jeśli różne → zmieniasz w kodzie (primary = ten z codegen; fallback =
     stary primary; tertiary = strukturalny XPath).
5. Analogicznie dla `LOGIN_SELECTORS` w `login_manager.py` (uruchom codegen
   na `https://www.olx.pl/konto/logowanie`).
6. Commit jako PR z opisem "SELECTORS: verified against live OLX YYYY-MM-DD".

**Regression test**: po każdej aktualizacji selektorów uruchom smoke tests
z README (Faza 2) + jeden test-run `dev_login` żeby potwierdzić.

## 6. Smoke tests (imports)

```bash
cd ~/Projects/marketia-olx-poster
source venv/bin/activate
python -c "from app.olx.browser_pool import create_browser, BrowserPool; print('browser_pool ok')"
python -c "from app.olx.humanizer import human_delay_seconds, human_type, human_click, human_action_pause; print('humanizer ok')"
python -c "from app.olx.selector_registry import SELECTORS, resolve, SelectorMissing; assert len(SELECTORS) >= 8; print('selector_registry ok')"
python -c "from app.olx.login_manager import is_logged_in, login, dev_login, LOGIN_SELECTORS; print('login_manager ok')"
python -c "from app.olx.listing_creator import ListingInput, ListingResult, create_listing, CaptchaDetected; print('listing_creator ok')"
python -c "from app.olx.pjs_selector import ensure_pjs_active, PJSUnavailable; print('pjs_selector ok')"
```

## 7. Ograniczenia Fazy 2

- **1 konto testowe** — Faza 4 uruchamia multi-account z pool.
- **Bez proxy** — decyzja user 2026-07-17. `account.proxy` w JSON schema
  pozostaje ale zawsze `null`.
- **Vision fallback nie działa** — Faza 6 (ENABLE_VISION_FALLBACK=false).
- **CAPTCHA = manual** — CaptchaDetected pauzuje flow; nie ma auto-solvera.

## 8. Co po zwalidowaniu

Zgłaszasz phase2-builder jeśli selektory różne od oczekiwań (może zaproponować
patch), inaczej przechodzisz do **Fazy 3** (queue worker + scheduler).
