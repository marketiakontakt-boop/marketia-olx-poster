"""Fallback: generuj master PNG (1024x1024) squircle + M + pin przez PIL.

Uruchamiane gdy ``qlmanage`` nie renderuje ``icon.svg`` czysto (typowy problem
z SVG font rendering na macOS). Wyjście: ``icon_1024.png`` w repo root — potem
``scripts/make_icon.sh`` pobiera to i buduje ``.icns``.

Wymaga PIL (Pillow). Instalacja: ``pip install Pillow``.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print(
        "PIL/Pillow niedostępny. Zainstaluj: pip install Pillow",
        file=sys.stderr,
    )
    raise SystemExit(1)


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "icon_1024.png"
SIZE = 1024
CORNER_RADIUS = 229  # 22.37% × 1024 = macOS squircle ratio
BG_TOP = (220, 38, 38)     # #dc2626
BG_BOTTOM = (185, 28, 28)  # #b91c1c


def _linear_gradient(w: int, h: int, top: tuple[int, int, int],
                     bottom: tuple[int, int, int]) -> Image.Image:
    """Wertykalno-diagonalny gradient (top-left → bottom-right)."""
    grad = Image.new("RGB", (w, h), color=top)
    px = grad.load()
    total = w + h
    for y in range(h):
        for x in range(w):
            t = (x + y) / total
            r = int(top[0] * (1 - t) + bottom[0] * t)
            g = int(top[1] * (1 - t) + bottom[1] * t)
            b = int(top[2] * (1 - t) + bottom[2] * t)
            px[x, y] = (r, g, b)
    return grad


def _squircle_mask(size: int, radius: int) -> Image.Image:
    """Squircle mask (rounded rect z korekcją macOS)."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (size, size)], radius=radius, fill=255)
    return mask


def _find_bold_font(px: int) -> ImageFont.ImageFont:
    """Szukaj Helvetica Bold lub systemowego bold. Fallback: default (mały)."""
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, px)
        except (OSError, IOError):
            continue
    print("WARNING: brak TTF font — używam default (M będzie mały)", file=sys.stderr)
    return ImageFont.load_default()


def _draw_pin(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """Rysuje biały kółko + czerwony pin marketplace."""
    # Białe tło koła
    draw.ellipse(
        [(cx - r, cy - r), (cx + r, cy + r)],
        fill=(255, 255, 255, 242),
    )
    # Pin — czerwona kropla (upraszczamy jako mały krąg + ostry trójkąt)
    pin_r = int(r * 0.55)
    draw.ellipse(
        [(cx - pin_r, cy - pin_r), (cx + pin_r, cy + pin_r - 5)],
        fill=BG_TOP,
    )
    # Punkt centralny
    dot = int(r * 0.15)
    draw.ellipse(
        [(cx - dot, cy - dot - 4), (cx + dot, cy + dot - 4)],
        fill=(255, 255, 255),
    )


def main() -> int:
    # 1. RGBA canvas
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # 2. Gradient background
    bg = _linear_gradient(SIZE, SIZE, BG_TOP, BG_BOTTOM).convert("RGBA")

    # 3. Squircle mask
    mask = _squircle_mask(SIZE, CORNER_RADIUS)

    # 4. Wklej bg z maską
    canvas.paste(bg, (0, 0), mask=mask)

    # 5. Litera M (biała, wielka)
    draw = ImageDraw.Draw(canvas)
    font = _find_bold_font(640)
    text = "M"
    # PIL >=10: textbbox; <10: textsize.
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        offset_x = bbox[0]
        offset_y = bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)
        offset_x = offset_y = 0
    x = (SIZE - tw) // 2 - offset_x
    y = (SIZE - th) // 2 - offset_y - 30
    draw.text((x, y), text, fill=(255, 255, 255), font=font)

    # 6. Pin w prawym dolnym rogu
    _draw_pin(draw, cx=820, cy=820, r=70)

    canvas.save(OUT, format="PNG")
    print(f"OK — {OUT} ({OUT.stat().st_size} bajtów)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
