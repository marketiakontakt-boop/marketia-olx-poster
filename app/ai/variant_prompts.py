"""Prompty Gemini dla generowania wariantów opisów OLX.

Wersja **v1** — do iteracji na REAL OUTPUT AUDIT (learning 2026-07-03).
Bump ``PROMPT_VERSION`` w ``app.config`` → cache auto-inwalidowany na odczycie.
"""
from __future__ import annotations

__all__ = [
    "DESCRIPTION_VARIANT_PROMPT",
    "TITLE_VARIANT_PROMPT",
    "VALIDATION_PROMPT",
    "FILLER_BLACKLIST",
]


#: Blacklista filler-adjectives — używana w prompt engineering i optional
#: guard w gemini_client (post-hoc check).
FILLER_BLACKLIST: tuple[str, ...] = (
    "PRAKTYCZNE",
    "NOWOCZESNE",
    "IDEALNE",
    "WYJĄTKOWE",
    "EKSKLUZYWNE",
    "ELEGANCKIE",
    "STYLOWE",
    "SUPER",
    "KOMFORTOWE",
    "WYGODNE",
    "TRWAŁE",
    "ATRAKCYJNE",
    "DESIGNERSKIE",
    "UNIWERSALNE",
    "MULTIFUNKCYJNE",
    "PRZEPIĘKNE",
    "MODERNISTYCZNE",
    "WYSOKIEJ JAKOŚCI",
    "DOMOWE",
)


DESCRIPTION_VARIANT_PROMPT = """Jesteś polskim copywriterem e-commerce specjalizującym się w OLX.

Twoje zadanie: przepisz JEDNO zdanie w poniższym opisie produktu tak, żeby brzmiało
naturalnie inaczej, ale ZACHOWAŁO sens, ton profesjonalny i wszystkie fakty
(ceny, wymiary, materiały, funkcje). Nie zmieniaj bulletpointów ani nagłówków.

MIASTO DOCELOWE: {city}
DZIELNICA: {location_variant}

ORYGINALNY OPIS:
{original_desc}

DODATEK MIASTA (do wplecenia w opis jeśli pasuje naturalnie, NIE oddzielnie):
{description_addon}

ZASADY:
1. Wybierz JEDNO zdanie ze środka opisu (nie pierwsze/ostatnie) i przepisz je.
2. Wplecz DODATEK MIASTA naturalnie — nie doklej na końcu jako blok osobny.
3. Zachowaj strukturę HTML jeśli była (bullet <ul><li>, nagłówki <h2>).
4. NIE dodawaj emoji, NIE dodawaj CTA typu "kup teraz", "sprawdź", "zobacz koniecznie".
5. NIE używaj kalki słowotwórczej (np. "ogrodowa" zamiast "do ogrodu" gdy dotyczy funkcji).
6. Zachowaj max ~1500 znaków (nie rozdmuchuj opisu).

Zwróć TYLKO przepisany opis. Bez wstępów typu "Oto opis:". Bez komentarza."""


TITLE_VARIANT_PROMPT = """Jesteś polskim copywriterem SEO Allegro/OLX.

Przepisz poniższy tytuł ogłoszenia zachowując wszystkie kluczowe frazy wyszukiwarki
(marka, model, funkcja), ale zmień kolejność słów lub zamień synonim jednego z nich
tak żeby brzmiało inaczej.

ORYGINALNY TYTUŁ: {original_title}
MIASTO DOCELOWE: {city}
SUFFIX MIASTA: {title_suffix}

ZASADY:
1. Max 70 znaków TOTALNIE (limit OLX).
2. Dodaj SUFFIX MIASTA na końcu jeśli mieści się w limicie, inaczej pomiń.
3. NIE używaj filler adjectives z blacklisty:
   PRAKTYCZNE, NOWOCZESNE, IDEALNE, WYJĄTKOWE, EKSKLUZYWNE, ELEGANCKIE, STYLOWE,
   SUPER, KOMFORTOWE, WYGODNE, TRWAŁE, ATRAKCYJNE, DESIGNERSKIE, UNIWERSALNE,
   MULTIFUNKCYJNE, PRZEPIĘKNE, MODERNISTYCZNE, WYSOKIEJ JAKOŚCI, DOMOWE.
4. Zachowaj brand + model + kluczową funkcję (np. "SOFA VILLAGO Milan 3-osobowa").
5. Preferuj przyimek+rzeczownik: "DO OGRODU" > "OGRODOWY" (gdy dotyczy funkcji).

Zwróć TYLKO tytuł. Nic więcej."""


VALIDATION_PROMPT = """Sprawdź czy wariant opisu OLX jest OK.

WARIANT:
{variant}

KRYTERIA:
- Długość ~1500 zn (max 3000)
- Struktura HTML poprawna (jeśli były bullet lists / nagłówki)
- Nie zawiera filler adjectives (patrz blacklist)
- Fakty zachowane vs oryginał (jeśli podano)

Zwróć JSON:
{{"ok": true|false, "issues": ["..."]}}"""
