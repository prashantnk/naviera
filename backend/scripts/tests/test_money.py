"""Unit tests for app.core.money (pure, no DB)."""

from decimal import Decimal

import pytest

from app.core.money import (
    ZERO_MONEY,
    is_billable_delta,
    money_to_float,
    to_money,
    to_weight,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (2.675, Decimal("2.68")),
        (2.665, Decimal("2.67")),
        (182.9, Decimal("182.90")),
        (0.1 + 0.2, Decimal("0.30")),
        ("1587.105", Decimal("1587.11")),
        (Decimal("-389.405"), Decimal("-389.41")),
        (7, Decimal("7.00")),
        (None, ZERO_MONEY),
        (" 12.5 ", Decimal("12.50")),
    ],
)
def test_to_money_rounds_half_up_to_the_paisa(raw, expected):
    assert to_money(raw) == expected
    assert to_money(raw).as_tuple().exponent == -2


@pytest.mark.parametrize("bad", [True, "abc", float("inf"), float("nan"), "Infinity"])
def test_to_money_rejects_non_numbers(bad):
    with pytest.raises(ValueError):
        to_money(bad)


def test_to_weight_keeps_grams():
    assert to_weight(35.5555) == Decimal("35.556")
    assert to_weight(None) == Decimal("0.000")
    assert to_weight("24") == Decimal("24.000")


def test_money_to_float_rounds_first():
    assert money_to_float(Decimal("187.215")) == 187.22
    assert money_to_float(None) == 0.0


@pytest.mark.parametrize(
    ("delta", "billable"),
    [(Decimal("0.004"), False), (Decimal("0.005"), True), (-0.01, True), (0, False), (389.4, True)],
)
def test_is_billable_delta(delta, billable):
    assert is_billable_delta(delta) is billable
