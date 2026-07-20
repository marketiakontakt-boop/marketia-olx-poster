#!/usr/bin/env bash
# scripts/make_icon.sh — SVG → icon.icns przy pomocy natywnych narzędzi macOS.
#
# Fallback: gdy qlmanage nie renderuje SVG czysto (font glitches, brak alfy),
# uruchom `python scripts/make_icon_png.py` żeby wygenerować master PNG przez PIL,
# a potem zapuść ten skrypt ponownie (wykryje istniejące icon_1024.png i skoczy).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SVG="icon.svg"
PNG_MASTER="icon_1024.png"
ICONSET="AppIcon.iconset"

if [[ ! -f "$PNG_MASTER" ]]; then
    if [[ ! -f "$SVG" ]]; then
        echo "FAIL: brak $SVG i $PNG_MASTER — nie mam z czego renderować icon" >&2
        exit 1
    fi

    echo "[1/4] SVG → PNG master (qlmanage 1024x1024)…"
    rm -f "${SVG%.svg}.png"
    qlmanage -t -s 1024 -o . "$SVG" >/dev/null 2>&1 || true

    if [[ -f "${SVG%.svg}.png" ]]; then
        mv "${SVG%.svg}.png" "$PNG_MASTER"
    else
        echo "qlmanage nie wygenerował PNG — spróbuj fallback:" >&2
        echo "  python scripts/make_icon_png.py" >&2
        exit 1
    fi
fi

echo "[2/4] Buduję iconset ($ICONSET)…"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$PNG_MASTER" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$PNG_MASTER" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
# 1024x1024 = icon_512x512@2x
cp "$PNG_MASTER" "$ICONSET/icon_512x512@2x.png"

echo "[3/4] Iconset → icon.icns…"
iconutil -c icns "$ICONSET" -o icon.icns

echo "[4/4] Cleanup tmp files…"
rm -rf "$ICONSET"
# PNG master zostawiamy — przydatny gdy user chce podglądnąć / re-run bez SVG.

echo
echo "OK — icon.icns wygenerowany ($(stat -f%z icon.icns) bajtów)"
