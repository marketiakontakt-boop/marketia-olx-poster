# Marketia OLX Poster

Aplikacja desktopowa macOS do masowego półautomatycznego wystawiania ogłoszeń na OLX.pl
z multi-account + multi-city support. TIER 5 (dropshipping + infra).

**Status:** Faza 5 (Polish + Packaging) — vision fallback, e2e tests, .app builder, first-run consent.

> Przeczytaj `DISCLAIMER.md` przed uruchomieniem. Aplikacja narusza OLX ToS
> i wymaga świadomej decyzji użytkownika. First-run modal blokuje uruchomienie
> bez świadomej akceptacji 7 punktów.

## Wymagania

- macOS 14+ (Sonoma, Sequoia)
- Python 3.12 (rekomendowane — py2app + Playwright stabilne; 3.13/3.14 eksperymentalne)
- ~4 GB miejsca (Chromium bundle w Fazie 5 packaging)

## Instalacja (dev)

```bash
cd ~/Projects/marketia-olx-poster
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

## Uruchomienie (dev)

```bash
source venv/bin/activate
python -m app.main
```

Pierwsze uruchomienie pokaże modal z 7 punktami DISCLAIMER. Musisz zaznaczyć
wszystkie i kliknąć "Akceptuję świadomie". Consent zapisany w `data/consent.json`.

## Dev login (per konto OLX)

Pierwsze logowanie każdego konta OLX robisz ręcznie (żeby zapisać cookies +
localStorage w `data/profiles/<account>/`):

```bash
python -m app.olx.login_manager --account marketia-glowne
# Otwiera Chromium headed, zaloguj się ręcznie, zamknij okno.
# Profil zapisany → następne wystawienia lecą z zalogowaną sesją.
```

## Testy

```bash
# Unit + integration (bez OLX creds):
pytest tests/unit tests/integration -v

# E2E mock-based (ban_detector, kill_switch — bez live OLX):
pytest tests/e2e/test_ban_detection.py tests/e2e/test_kill_switch.py -v

# E2E live (wymaga env vars):
export OLX_TEST_EMAIL="testowe@konto.pl"
export OLX_TEST_PASSWORD="..."
pytest tests/e2e/ -v
```

Testy bez env vars są **skipowane** (nie failują) — bezpieczne w CI.

## Build .app (Faza 5)

```bash
source venv/bin/activate
pip install py2app
bash build.sh
open "dist/Marketia OLX Poster.app"
```

Bez `DEVELOPER_ID_APPLICATION` env var: ad-hoc signing. Przy pierwszym
uruchomieniu Ctrl+Klik → "Otwórz" żeby ominąć Gatekeeper.

Z Developer ID + Apple ID env vars — build.sh submituje do notarytool i staple'uje
(5-15 min). Wynik: signed + notarized .app, otwiera się dwoma kliknięciami.

## Struktura

```
app/          — kod aplikacji (data, olx, queue, monitor, ai, security, gui)
data/         — city_templates.json, profiles/, accounts.json.encrypted, consent.json
output/       — screenshots, logs, reports (gitignored, retencja 30 dni)
tests/        — unit/, integration/, e2e/
scripts/      — make_icon.sh, make_icon_png.py
icon.svg      — squircle #dc2626 + M + pin (marketplace multi-city)
icon.icns     — generated
build.sh      — .app builder (py2app + codesign + notarize)
setup.py      — py2app config
entitlements.plist — JIT allow (Chromium), keychain, network client
```

## Feature flags (.env)

```
ENABLE_VISION_FALLBACK=false   # Claude Sonnet 4.6 Vision gdy 3-level selectors fail
ENABLE_GEMINI_VARIANTS=true    # multi-city variants przez Gemini
ANTHROPIC_API_KEY=sk-...       # wymagane gdy VISION_FALLBACK=true
GEMINI_API_KEY=AIza...
```

## Kluczowe dokumenty

- `DISCLAIMER.md` — 7 ethical flags (OLX ToS, multi-account, humanizer, PII)
- `~/Documents/_meta/marketia-olx-poster/SPEC.md` — pełna specyfikacja techniczna
- `~/Documents/_meta/marketia-olx-poster/phase5_packaging_draft.md` — packaging notes
