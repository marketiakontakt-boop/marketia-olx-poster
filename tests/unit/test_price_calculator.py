"""Unit testy dla app/data/price_calculator.py — 100% pure functions."""
from __future__ import annotations

import pytest

from app.data.price_calculator import PriceError, calculate_price


class TestCalculatePrice:
    def test_basic(self):
        assert calculate_price(100.0) == 100.0

    def test_int_base(self):
        assert calculate_price(50) == 50.0

    def test_positive_city_offset(self):
        assert calculate_price(100.0, city_offset=10) == 110.0

    def test_negative_city_offset(self):
        assert calculate_price(100.0, city_offset=-15) == 85.0

    def test_markup_5pct(self):
        assert calculate_price(100.0, markup_pct=0.05) == 105.0

    def test_negative_markup(self):
        assert calculate_price(100.0, markup_pct=-0.20) == 80.0

    def test_offset_and_markup_combined(self):
        # (100 + 10) * 1.05 = 115.50
        assert calculate_price(100.0, city_offset=10, markup_pct=0.05) == 115.5

    def test_rounding_to_2_decimals(self):
        # (100 + 3) * 1.037 = 106.811 → 106.81
        assert calculate_price(100.0, city_offset=3, markup_pct=0.037) == 106.81

    def test_zero_base_raises(self):
        with pytest.raises(PriceError, match="base_price musi być > 0"):
            calculate_price(0.0)

    def test_negative_base_raises(self):
        with pytest.raises(PriceError):
            calculate_price(-50.0)

    def test_string_base_raises(self):
        with pytest.raises(PriceError):
            calculate_price("100")  # type: ignore[arg-type]

    def test_markup_below_minus_half_raises(self):
        with pytest.raises(PriceError, match="markup_pct nie może być < -0.5"):
            calculate_price(100.0, markup_pct=-0.6)

    def test_result_zero_or_negative_raises(self):
        # base=100, offset=-100 → 0 → raises
        with pytest.raises(PriceError, match="Cena końcowa <= 0"):
            calculate_price(100.0, city_offset=-100)

    def test_result_forced_negative_via_offset(self):
        with pytest.raises(PriceError):
            calculate_price(50.0, city_offset=-100)
