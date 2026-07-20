"""Gemini 2.5 Flash client dla generowania wariantów opisów/tytułów.

**KRYTYCZNE CONFIG** (learning z domain scanner 2026-07-03):

- ``thinking_budget=0`` HARDCODED — bez tego output ~360 zn zamiast 800+.
  Config gubi się jeśli przekazany dynamicznie, więc jest wbudowany na sztywno
  w helper (nie param).
- ``max_output_tokens=8192`` — spory margines.
- ``temperature=0.7`` — chcemy wariacji.

Retry policy: MAX_RETRIES=3, backoff [1, 3, 8] s.
Po wyczerpaniu retries → ``GeminiVariantFailed``. Wyższa warstwa może użyć
``template_variant_fallback`` (deterministic, bez AI).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from typing import Any

from ..config import GEMINI_API_KEY
from .variant_prompts import DESCRIPTION_VARIANT_PROMPT, TITLE_VARIANT_PROMPT

__all__ = [
    "GeminiClient",
    "GeminiVariantFailed",
    "MAX_RETRIES",
    "BACKOFF_S",
    "MODEL_NAME",
    "template_variant_fallback",
]

_LOG = logging.getLogger("marketia.ai.gemini_client")

MODEL_NAME: str = "gemini-2.5-flash"
MAX_RETRIES: int = 3
BACKOFF_S: tuple[int, ...] = (1, 3, 8)


class GeminiVariantFailed(RuntimeError):
    """Rzucane po 3 nieudanych próbach wygenerowania wariantu."""


class GeminiClient:
    """Cienki wrapper na ``google.genai`` — async generation + retry.

    Uwaga: SDK oferuje sync/async przez ``client.models.generate_content`` /
    ``client.aio.models.generate_content``. Używamy async wersji.
    """

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError(
                "GEMINI_API_KEY nie ustawione (ani w .env, ani jako argument)."
            )
        # Late import — pozwala testom bez google-genai zainstalowanego.
        from google import genai  # type: ignore

        self._genai = genai
        self._client = genai.Client(api_key=key)

    # ---- Config builder --------------------------------------------------

    def _build_config(self) -> Any:
        """Buduje ``GenerateContentConfig`` z HARDCODED thinking_budget=0.

        Learning (2026-07-03): dynamic thinking_budget jest gubione, nawet gdy
        w dict pojawia się poprawny klucz. Wbudowujemy na sztywno w klienta.
        """
        from google.genai import types  # type: ignore

        return types.GenerateContentConfig(
            temperature=0.7,
            maxOutputTokens=8192,
            thinkingConfig=types.ThinkingConfig(thinkingBudget=0),
        )

    # ---- Core call with retry -------------------------------------------

    async def _call_with_retry(self, prompt: str) -> str:
        """Async call z retry [1, 3, 8] s backoff. Raise GeminiVariantFailed."""
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                config = self._build_config()
                resp = await self._client.aio.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=config,
                )
                text = getattr(resp, "text", None)
                if not text or not text.strip():
                    raise ValueError("Gemini zwrócił pusty text")
                return text.strip()
            except Exception as exc:
                last_error = exc
                _LOG.warning(
                    "Gemini attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                )
                traceback.print_exc(file=sys.stdout)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_S[attempt])
        raise GeminiVariantFailed(
            f"Gemini failed after {MAX_RETRIES} attempts: {last_error}"
        )

    # ---- Public API ------------------------------------------------------

    async def generate_description_variant(
        self,
        original_desc: str,
        city: str,
        location: str,
        description_addon: str,
    ) -> str:
        """Wygeneruj wariant opisu dla miasta.

        Raises:
            GeminiVariantFailed: po 3 nieudanych próbach.
        """
        prompt = DESCRIPTION_VARIANT_PROMPT.format(
            city=city,
            location_variant=location,
            original_desc=original_desc,
            description_addon=description_addon,
        )
        return await self._call_with_retry(prompt)

    async def generate_title_variant(
        self,
        original_title: str,
        city: str,
        title_suffix: str,
    ) -> str:
        """Wygeneruj wariant tytułu dla miasta (max 70 znaków, OLX limit)."""
        prompt = TITLE_VARIANT_PROMPT.format(
            original_title=original_title,
            city=city,
            title_suffix=title_suffix,
        )
        text = await self._call_with_retry(prompt)
        # Hard cap 70 znaków defensywnie — nawet gdy prompt zignorowany.
        if len(text) > 70:
            _LOG.warning("Gemini title >70 znaków (%d), przycinam", len(text))
            text = text[:70].rstrip()
        return text


# --- Deterministic fallback (bez AI) --------------------------------------

def template_variant_fallback(
    original_desc: str,
    city_template: dict[str, Any],
    iteration: int,
) -> str:
    """Prosty template fallback — naprzemiennie prepend/append addon.

    Zero AI calls, gwarantuje że zawsze mamy wariant. Używane gdy Gemini
    padnie z quota / rate limit / błąd sieci.

    Args:
        original_desc: oryginalny opis.
        city_template: dict z ``description_addon``.
        iteration: numer wariantu (parzysty → prepend, nieparzysty → append).

    Returns:
        Nowy opis (str).
    """
    addon = str(city_template.get("description_addon") or "").strip()
    if not addon:
        return original_desc
    if iteration % 2 == 0:
        return f"{addon}\n\n{original_desc}"
    return f"{original_desc}\n\n{addon}"
