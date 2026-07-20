"""Vision fallback — Claude Sonnet 4.6 analyzes screenshot gdy selectors fail.

Ostatnia warstwa obrony gdy 3-level selector chain z ``selector_registry`` rzuci
``SelectorMissing``. Robi screenshot bieżącej strony, wysyła do Claude Vision
i prosi o sugerowany DOM selector. Zwraca JSON z listą propozycji + confidence.

Wywoływane rzadko (~10-50/miesiąc gdy OLX robi A/B testy formularza). Koszt
~$0.005/call. Alternatywa: 24-48h downtime na ręczną inspekcję DOM.

Feature flag: ``ENABLE_VISION_FALLBACK=true`` w ``.env``. Domyślnie wyłączone.

Sugestie logowane do ``output/logs/vision_suggestions.jsonl`` — codzienny raport
zawiera podsumowanie (user weryfikuje → dodaje do ``selector_registry``).
"""
from __future__ import annotations

import base64
import json
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..config import LOGS_DIR

if TYPE_CHECKING:  # pragma: no cover
    from patchright.async_api import Page

__all__ = ["vision_fallback_suggest", "VisionFailed", "is_enabled"]

_LOG = logging.getLogger("marketia.olx.vision_fallback")
_SUGGESTIONS_FILE = LOGS_DIR / "vision_suggestions.jsonl"

# Model — Sonnet 4.6 (Vision-capable, koszt-efektywny).
_MODEL = "claude-sonnet-4-6"


class VisionFailed(RuntimeError):
    """Rzucane gdy Claude API failuje lub zwraca nieużyteczną odpowiedź."""


def is_enabled() -> bool:
    """Feature flag przez env: ``ENABLE_VISION_FALLBACK=true``.

    Czytane fresh z env (nie z ``config.ENABLE_VISION_FALLBACK`` który jest
    frozen at import time) — pozwala on/off runtime bez restartu.
    """
    return os.getenv("ENABLE_VISION_FALLBACK", "false").lower() == "true"


def _extract_json(text: str) -> str:
    """Wyciąga JSON z odpowiedzi Claude (może zawierać markdown fence)."""
    text = text.strip()
    if text.startswith("```"):
        # Usuń otwierający fence: ```json lub ```
        parts = text.split("```")
        # parts: ['', 'json\n{...}\n', '']  albo  ['', '{...}\n', '']
        if len(parts) >= 2:
            body = parts[1]
            if body.lstrip().startswith("json"):
                body = body.lstrip()[4:]
            return body.strip()
    return text


async def vision_fallback_suggest(
    page: "Page",
    element_description: str,
    context_hint: str | None = None,
) -> dict[str, Any]:
    """Analyze screenshot, suggest DOM selectors dla wskazanego elementu.

    Args:
        page: Playwright ``Page`` z załadowaną stroną OLX.
        element_description: opis szukanego elementu, np. "input dla tytułu".
        context_hint: dodatkowy kontekst, np. "powyżej pola opisu".

    Returns:
        ``{
            "selectors": ["primary", "fallback1", "fallback2"],
            "rationale": "krótki opis dlaczego",
            "confidence": 0.0-1.0,
            "screenshot_path": "output/logs/vision_XXXXXXXX.png",
        }``

    Raises:
        VisionFailed: gdy vision disabled, brak klucza API, API error,
            malformed JSON lub pusta lista selektorów.
    """
    if not is_enabled():
        raise VisionFailed("Vision fallback disabled (ENABLE_VISION_FALLBACK=false)")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise VisionFailed("ANTHROPIC_API_KEY not set")

    # 1. Screenshot (nie full_page — element powinien być w viewport).
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    screenshot_path = LOGS_DIR / f"vision_{timestamp}.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(screenshot_path), full_page=False)
    except Exception as exc:
        raise VisionFailed(f"screenshot failed: {exc}") from exc

    with open(screenshot_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # 2. HTML snippet — crop do 8000 chars, oszczędź tokeny.
    try:
        html = await page.content()
    except Exception as exc:
        _LOG.debug("page.content failed: %s", exc)
        html = ""
    html_snippet = html[:8000]

    # 3. Anthropic client
    try:
        from anthropic import Anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise VisionFailed(f"anthropic SDK not installed: {exc}") from exc

    client = Anthropic(api_key=api_key)

    prompt = f"""Szukam elementu DOM na screenshot'cie OLX.

ELEMENT SZUKANY: {element_description}
KONTEKST: {context_hint or 'brak'}

FRAGMENT HTML (pierwsze 8000 zn):
{html_snippet}

Zwróć JSON:
{{
  "selectors": ["<data-testid=... lub CSS>", "<fallback1>", "<fallback2>"],
  "rationale": "1-2 zdania dlaczego te selectors są prawdopodobne",
  "confidence": <0.0-1.0>
}}

Zwróć TYLKO JSON, bez komentarza."""

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as exc:
        raise VisionFailed(f"Anthropic API error: {exc}") from exc

    # 4. Parse — Claude czasem wraps w ```json fence.
    try:
        raw_text = response.content[0].text  # type: ignore[union-attr]
    except (AttributeError, IndexError) as exc:
        raise VisionFailed(f"unexpected response shape: {exc}") from exc

    text = _extract_json(raw_text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisionFailed(
            f"Vision returned invalid JSON: {exc}\nText: {text[:200]}"
        ) from exc

    selectors = result.get("selectors")
    if not isinstance(selectors, list) or not selectors:
        raise VisionFailed(f"Vision zwróciło pustą listę selektorów: {result}")

    result["screenshot_path"] = str(screenshot_path)

    # 5. Log do JSONL.
    _SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "element": element_description,
        "context": context_hint,
        "suggestions": selectors,
        "rationale": result.get("rationale"),
        "confidence": result.get("confidence"),
        "screenshot": str(screenshot_path),
    }
    with _SUGGESTIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    _LOG.info(
        "Vision suggestion for %r: %s (confidence=%.2f)",
        element_description,
        selectors[0],
        float(result.get("confidence") or 0.0),
    )

    return result
