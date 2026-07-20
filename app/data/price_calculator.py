"""Kalkulacja ceny per miasto.

Prosty model: cena bazowa + offset miasta + markup %. Walidacja twarda —
zwracamy błąd zamiast cichego 0.0.
"""
from __future__ import annotations

__all__ = ["calculate_price", "PriceError"]


class PriceError(ValueError):
    """Rzucane gdy input lub wynik są nieprawidłowe."""


def calculate_price(
    base_price: float,
    city_offset: int = 0,
    markup_pct: float = 0.0,
) -> float:
    """Zwraca cenę końcową zaokrągloną do 2 miejsc.

    Args:
        base_price: cena bazowa produktu (> 0).
        city_offset: offset kwotowy w PLN (może być ujemny, np. konkurencja).
        markup_pct: dodatkowy narzut procentowy, np. 0.05 = +5%.

    Raises:
        PriceError: gdy `base_price <= 0` lub wynik ≤ 0.
    """
    if not isinstance(base_price, (int, float)) or base_price <= 0:
        raise PriceError(f"base_price musi być > 0, otrzymano: {base_price!r}")
    if not isinstance(markup_pct, (int, float)) or markup_pct < -0.5:
        raise PriceError(f"markup_pct nie może być < -0.5, otrzymano: {markup_pct!r}")

    price = (base_price + float(city_offset)) * (1.0 + float(markup_pct))
    price = round(price, 2)

    if price <= 0:
        raise PriceError(
            f"Cena końcowa <= 0 (base={base_price}, offset={city_offset}, "
            f"markup={markup_pct}, wynik={price})"
        )
    return price
