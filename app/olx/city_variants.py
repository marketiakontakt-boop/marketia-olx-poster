"""Generator wariantów per miasto.

Faza 3 krok 3.1.

Dla każdego miasta (z ``data/city_templates.json``) generuje ``VariantSpec``:

- title = f"{original_title} {title_suffix}" trim'd do 70 znaków (OLX limit)
- description = naprzemiennie prepend/append ``description_addon``
  (parzysty iteration counter → prepend, nieparzysty → append)
- location = random z ``location_variants``
- price = base + ``price_offset``

Hash-dedup: SHA256(title|description|city) — jeśli hash już w ``variant_cache``
na tym samym prompt_version → skip (cached). Cache versioning enforced NA
ODCZYCIE (variant_cache_get zwraca None gdy prompt_version się różni).

Streaming save: po każdym wygenerowanym wariancie od razu save do cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import CITY_TEMPLATES_PATH, PROMPT_VERSION
from ..data import shared_db

__all__ = [
    "VariantSpec",
    "CityTemplateMissing",
    "load_city_templates",
    "cache_key",
    "content_hash",
    "generate_variants",
    "get_all_cities",
]

_LOG = logging.getLogger("marketia.olx.city_variants")

#: OLX title limit — hard cap 70 znaków (spec 5).
OLX_TITLE_MAX: int = 70


class CityTemplateMissing(RuntimeError):
    """Brak wpisu dla miasta w ``city_templates.json``."""


# --- Data class -----------------------------------------------------------

@dataclass(slots=True)
class VariantSpec:
    """Pojedynczy wariant ogłoszenia — jedno miasto, jeden target."""

    sku: str
    title: str
    description: str
    price_pln: float
    city: str
    location_variant: str
    image_paths: list[Path]
    category_hint: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Serializacja do cache (variant_cache.variant_json)."""
        return {
            "sku": self.sku,
            "title": self.title,
            "description": self.description,
            "price_pln": self.price_pln,
            "city": self.city,
            "location_variant": self.location_variant,
            "image_paths": [str(p) for p in self.image_paths],
            "category_hint": self.category_hint,
            "metadata": self.metadata,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "VariantSpec":
        return cls(
            sku=payload["sku"],
            title=payload["title"],
            description=payload["description"],
            price_pln=float(payload["price_pln"]),
            city=payload["city"],
            location_variant=payload["location_variant"],
            image_paths=[Path(p) for p in payload.get("image_paths", [])],
            category_hint=payload.get("category_hint", ""),
            metadata=payload.get("metadata", {}),
        )


# --- Loader ---------------------------------------------------------------

_CITY_TEMPLATES_CACHE: dict[str, Any] | None = None


def load_city_templates(path: Path | None = None) -> dict[str, Any]:
    """Wczytuje ``city_templates.json``. Cache in-memory (idempotent).

    Struktura:
        {"cities": {"Warszawa": {...}, ...}, "assignments_suggestion": {...}}
    """
    global _CITY_TEMPLATES_CACHE
    if _CITY_TEMPLATES_CACHE is not None and path is None:
        return _CITY_TEMPLATES_CACHE
    p = path or CITY_TEMPLATES_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        _LOG.error("city_templates.json nie istnieje: %s", p)
        raise
    except json.JSONDecodeError as exc:
        _LOG.error("city_templates.json invalid JSON: %s", exc)
        raise
    if path is None:
        _CITY_TEMPLATES_CACHE = data
    return data


def get_all_cities(path: Path | None = None) -> list[str]:
    """Zwraca listę wszystkich zdefiniowanych miast z `city_templates.json`.

    Używane przez GUI wizard (Konta → miasta checkboxy). Fallback: pusta lista
    gdy plik nie istnieje / nie ma sekcji cities.
    """
    try:
        data = load_city_templates(path)
    except (FileNotFoundError, ValueError):
        return []
    cities = data.get("cities") or {}
    return sorted(cities.keys())


def _city_data(templates: dict[str, Any], city: str) -> dict[str, Any]:
    """Zwraca sekcję ``cities[city]`` lub rzuca ``CityTemplateMissing``."""
    cities = templates.get("cities") or {}
    entry = cities.get(city)
    if not entry:
        raise CityTemplateMissing(f"Brak template dla miasta: {city}")
    return entry


# --- Hash + cache key -----------------------------------------------------

def cache_key(sku: str, city: str, prompt_version: str = PROMPT_VERSION) -> str:
    """Klucz cache dla wariantu opisu.

    Bump ``prompt_version`` → cache automatycznie unieważniony
    (variant_cache_get sprawdza prompt_version przy odczycie).
    """
    raw = f"{sku}|{city}|{prompt_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def content_hash(title: str, description: str, city: str) -> str:
    """SHA256 dedup — content-based, wykrywa duplikaty across variants."""
    raw = f"{title}|{description}|{city}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# --- Generation -----------------------------------------------------------

def _trim_title(title: str, max_len: int = OLX_TITLE_MAX) -> str:
    """Trimuje tytuł do ``max_len`` bez rozcinania słowa (jeśli można)."""
    if len(title) <= max_len:
        return title
    # Znajdź ostatnią spację przed limitem — czystszy trim.
    cut = title[:max_len].rstrip()
    last_space = cut.rfind(" ")
    if last_space > max_len - 15:
        cut = cut[:last_space].rstrip()
    return cut


def _build_title(original_title: str, city_entry: dict[str, Any]) -> str:
    suffix = str(city_entry.get("title_suffix") or "").strip()
    if not suffix:
        return _trim_title(original_title)
    combined = f"{original_title} {suffix}".strip()
    return _trim_title(combined)


def _build_description(
    original_desc: str,
    city_entry: dict[str, Any],
    iteration: int,
) -> str:
    """Naprzemiennie prepend/append `description_addon`.

    - iteration % 2 == 0 → prepend
    - iteration % 2 == 1 → append
    """
    addon = str(city_entry.get("description_addon") or "").strip()
    if not addon:
        return original_desc
    if iteration % 2 == 0:
        return f"{addon}\n\n{original_desc}"
    return f"{original_desc}\n\n{addon}"


def _pick_location(city_entry: dict[str, Any], rng: random.Random) -> str:
    variants = city_entry.get("location_variants") or []
    if not variants:
        return ""
    return rng.choice(variants)


def _generate_single(
    product: dict[str, Any],
    city: str,
    city_entry: dict[str, Any],
    iteration: int,
    rng: random.Random,
) -> VariantSpec:
    """Buduje pojedynczy VariantSpec z template'u (bez AI, deterministic)."""
    sku = str(product.get("sku") or product.get("id") or "")
    original_title = str(product.get("title") or product.get("name") or "")
    original_desc = str(product.get("description") or "")
    base_price = float(product.get("price") or 0)
    price_offset = float(city_entry.get("price_offset") or 0)
    category_hint = str(product.get("category_hint") or product.get("category") or "")

    # Image paths — akceptujemy str/Path listę.
    raw_imgs = product.get("image_paths") or product.get("images") or []
    image_paths: list[Path] = []
    for entry in raw_imgs:
        if isinstance(entry, Path):
            image_paths.append(entry)
        elif isinstance(entry, str) and entry.strip():
            image_paths.append(Path(entry))

    title = _build_title(original_title, city_entry)
    description = _build_description(original_desc, city_entry, iteration)
    location = _pick_location(city_entry, rng)
    price_pln = base_price + price_offset

    return VariantSpec(
        sku=sku,
        title=title,
        description=description,
        price_pln=price_pln,
        city=city,
        location_variant=location,
        image_paths=image_paths,
        category_hint=category_hint,
        metadata={
            "iteration": iteration,
            "prompt_version": PROMPT_VERSION,
            "price_offset_applied": price_offset,
            "postal_code_prefix": city_entry.get("postal_code_prefix"),
            "delivery_options": city_entry.get("delivery_options") or [],
        },
    )


def generate_variants(
    product: dict[str, Any],
    cities: list[str],
    *,
    prompt_version: str = PROMPT_VERSION,
    account_name: str | None = None,
    rng_seed: int | None = None,
    templates_path: Path | None = None,
) -> list[VariantSpec]:
    """Generuje warianty per miasto z template-based fallback (bez AI).

    Streaming save do ``variant_cache`` po każdym wariancie.

    Cache hit (variant_cache_get zwraca payload z pasującym prompt_version) →
    używamy cached. Cache miss → generujemy, zapisujemy, dedup przez
    content_hash (jeśli hash już istnieje na innym miejcu → force regenerate
    z odchyłem iteracji o +1).

    Args:
        product: dict produktu (min. sku, title, description, price, images).
        cities: lista miast do wygenerowania.
        prompt_version: obecna wersja promptu (default z config).
        account_name: opcjonalne — dla logów.
        rng_seed: opcjonalne — do testów deterministic.
        templates_path: opcjonalne — override ścieżki templates (do testów).

    Returns:
        list[VariantSpec] — dokładnie tyle wariantów ile poprawnie sgenerowano.
        Miasta bez templates zostaną pominięte (log warning).
    """
    templates = load_city_templates(templates_path)
    rng = random.Random(rng_seed) if rng_seed is not None else random.Random()

    sku = str(product.get("sku") or product.get("id") or "")
    if not sku:
        _LOG.warning("generate_variants: produkt bez SKU, pomijam całość")
        return []

    variants: list[VariantSpec] = []
    seen_content_hashes: set[str] = set()

    for iteration, city in enumerate(cities):
        try:
            city_entry = _city_data(templates, city)
        except CityTemplateMissing as exc:
            _LOG.warning("Skip %s: %s", city, exc)
            continue

        key = cache_key(sku, city, prompt_version)

        # 1. Cache read — versioning enforced NA ODCZYCIE.
        cached = shared_db.variant_cache_get(key, prompt_version=prompt_version)
        if cached is not None:
            try:
                variant = VariantSpec.from_json(cached)
                # Nadpisz image_paths z aktualnego produktu (mogą się zmienić
                # bez zmiany PROMPT_VERSION — folder photos może być inny).
                variant.image_paths = [
                    Path(p)
                    for p in (product.get("image_paths") or product.get("images") or [])
                    if p
                ] or variant.image_paths
                ch = content_hash(variant.title, variant.description, variant.city)
                if ch not in seen_content_hashes:
                    seen_content_hashes.add(ch)
                    variants.append(variant)
                    _LOG.debug(
                        "cache hit sku=%s city=%s account=%s", sku, city, account_name
                    )
                    continue
                # Kolizja hash — regeneruj poniżej.
                _LOG.debug("cache hit ale content_hash collision, regen sku=%s city=%s", sku, city)
            except Exception:
                traceback.print_exc(file=sys.stdout)
                _LOG.warning("cache payload deserialization failed, regen")

        # 2. Generation — template-based fallback (bez AI).
        # Try do 3 razy z rosnącym iteration counter (żeby uniknąć kolizji).
        variant: VariantSpec | None = None
        for attempt in range(3):
            candidate = _generate_single(
                product, city, city_entry, iteration + attempt, rng
            )
            ch = content_hash(candidate.title, candidate.description, candidate.city)
            if ch not in seen_content_hashes:
                seen_content_hashes.add(ch)
                variant = candidate
                break
            _LOG.debug(
                "content_hash collision attempt=%d sku=%s city=%s, retry",
                attempt,
                sku,
                city,
            )

        if variant is None:
            _LOG.warning(
                "Nie udało się wygenerować unikalnego wariantu sku=%s city=%s",
                sku,
                city,
            )
            continue

        # 3. Streaming save cache (learning: po KAŻDYM wariancie, nie po batchu).
        try:
            shared_db.variant_cache_save(
                cache_hash=key,
                sku=sku,
                city=city,
                variant=variant.to_json(),
                prompt_version=prompt_version,
            )
        except Exception:
            traceback.print_exc(file=sys.stdout)
            _LOG.warning("variant_cache_save failed sku=%s city=%s", sku, city)

        variants.append(variant)

    return variants
