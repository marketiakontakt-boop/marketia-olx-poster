#!/usr/bin/env bash
# build.sh — buduje ``dist/Marketia OLX Poster.app`` przez py2app.
#
# Wymaga: aktywnego venv, deps zainstalowane (`pip install -r requirements.txt`),
# oraz ``py2app`` (`pip install py2app`).
#
# Opcjonalne env vars dla codesign + notarize:
#   DEVELOPER_ID_APPLICATION   — cert ID, np. "Developer ID Application: Jan Kowalski (ABC1234567)"
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD — do notarytool
#
# Brak DEVELOPER_ID_APPLICATION → ad-hoc signing (unsigned; user Ctrl+Klik przy pierwszym uruchomieniu).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=== Marketia OLX Poster — Build ==="

# 1. Sanity checks
if [[ "$(python --version 2>&1)" != "Python 3.12."* ]]; then
    echo "WARNING: Python 3.12 zalecany. Aktualnie: $(python --version)"
    echo "(3.13+ może działać ale py2app na tych wersjach jest eksperymentalne)"
fi

if ! python -c "import py2app" 2>/dev/null; then
    echo "FAIL: py2app nie zainstalowany. pip install py2app" >&2
    exit 1
fi

# 2. Cleanup poprzedni build
rm -rf build dist

# 3. Generate icon jeśli brak
if [[ ! -f icon.icns ]]; then
    echo "Generuję icon.icns…"
    if [[ ! -f icon_1024.png ]] && python -c "import PIL" 2>/dev/null; then
        python scripts/make_icon_png.py
    fi
    bash scripts/make_icon.sh
fi

# 4. Playwright chromium install
echo "Ensuring Playwright chromium is installed…"
python -m playwright install chromium

# 5. py2app build
echo "Running py2app…"
python setup.py py2app --arch universal2

# 6. Verify bundle
APP_PATH="dist/Marketia OLX Poster.app"
if [[ ! -d "$APP_PATH" ]]; then
    echo "FAIL: .app nie zbudowany" >&2
    exit 1
fi

# 7. Bundle size check
SIZE_MB=$(du -sm "$APP_PATH" | awk '{print $1}')
echo "Bundle size: ${SIZE_MB} MB"
if [[ "$SIZE_MB" -gt 500 ]]; then
    echo "WARNING: bundle > 500MB (Chromium bundled). Rozważ 'download on first run' fallback."
fi

# 8. Codesign
if [[ -n "${DEVELOPER_ID_APPLICATION:-}" ]]; then
    echo "Codesigning with: $DEVELOPER_ID_APPLICATION"
    codesign --force --deep --sign "$DEVELOPER_ID_APPLICATION" \
        --options runtime \
        --entitlements entitlements.plist \
        "$APP_PATH"

    if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PASSWORD:-}" ]]; then
        echo "Submitting for notarization (może potrwać 5-15 min)…"
        ditto -c -k --keepParent "$APP_PATH" "dist/Marketia OLX Poster.zip"
        xcrun notarytool submit "dist/Marketia OLX Poster.zip" \
            --apple-id "$APPLE_ID" \
            --team-id "$APPLE_TEAM_ID" \
            --password "$APPLE_APP_PASSWORD" \
            --wait
        xcrun stapler staple "$APP_PATH"
        echo "Notarization complete"
    fi
else
    echo "Ad-hoc signing (unsigned — user Ctrl+Klik przy pierwszym uruchomieniu)"
    codesign --force --deep --sign - "$APP_PATH"
fi

# 9. Register with LaunchServices (odswiez ikonkę w Finderze)
BUNDLE_ID="com.marketia.olxposter"
tccutil reset All "$BUNDLE_ID" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$APP_PATH" 2>/dev/null || true
touch "$APP_PATH"

echo
echo "=== BUILD COMPLETE ==="
echo "App: $APP_PATH"
echo "Size: ${SIZE_MB} MB"
echo
echo "Test:"
echo "  open '$APP_PATH'"
echo
echo "Jeśli macOS Gatekeeper blokuje (unsigned):"
echo "  Ctrl+Klik → Otwórz → Otwórz (raz, potem działa normalnie)"
