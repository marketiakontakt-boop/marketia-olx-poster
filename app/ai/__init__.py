"""AI package.

Faza 3: ``gemini_client`` + ``variant_prompts`` dostarczone.
"""

from .gemini_client import (
    BACKOFF_S,
    MAX_RETRIES,
    MODEL_NAME,
    GeminiClient,
    GeminiVariantFailed,
    template_variant_fallback,
)
from .variant_prompts import (
    DESCRIPTION_VARIANT_PROMPT,
    FILLER_BLACKLIST,
    TITLE_VARIANT_PROMPT,
    VALIDATION_PROMPT,
)

__all__ = [
    "GeminiClient",
    "GeminiVariantFailed",
    "MAX_RETRIES",
    "BACKOFF_S",
    "MODEL_NAME",
    "template_variant_fallback",
    "DESCRIPTION_VARIANT_PROMPT",
    "TITLE_VARIANT_PROMPT",
    "VALIDATION_PROMPT",
    "FILLER_BLACKLIST",
]
