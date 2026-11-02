"""
Exact money and weight arithmetic for every new money path (plan §2.0 "Money").

Why: legacy price columns are DOUBLE PRECISION, and float sums drift by a paisa
(0.1 + 0.2 != 0.3). New code converts every amount with `to_money()` first and
does arithmetic on `Decimal`, rounding half-up to the paisa exactly once.

Spring analogy: a small static utility class like `MoneyUtils` built on
`BigDecimal.setScale(2, RoundingMode.HALF_UP)`.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Union

MONEY_QUANT = Decimal("0.01")
"""Money is kept to the paisa (2 decimal places)."""

WEIGHT_QUANT = Decimal("0.001")
"""Weights are kept to the gram (3 decimal places of a kilogram)."""

ZERO_MONEY = Decimal("0.00")
"""Canonical zero amount."""

MIN_BILLABLE_DELTA = Decimal("0.01")
"""Deltas below one paisa are rounding noise and are never billed."""

MoneyLike = Union[Decimal, float, int, str, None]
"""Anything a caller may hand us: DB floats, NUMERIC decimals, ints or strings."""


def _to_decimal(value: MoneyLike) -> Decimal:
    """
    Converts a money-like value to an unrounded Decimal.

    Floats go through `str()` so 182.9 becomes Decimal("182.9") rather than the
    binary expansion 182.900000000000005684.

    Args:
        value: The raw value (None counts as zero).

    Returns:
        The Decimal value.

    Raises:
        ValueError: the value is not a finite number.
    """
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool):
        raise ValueError("A boolean is not a money amount.")
    elif isinstance(value, (int, float)):
        result = Decimal(str(value))
    else:
        try:
            result = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"Not a number: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Not a finite number: {value!r}")
    return result


def to_money(value: MoneyLike) -> Decimal:
    """
    Rounds a money-like value half-up to the paisa.

    Args:
        value: Decimal, float, int, numeric string or None (zero).

    Returns:
        A Decimal with exactly two decimal places, e.g. to_money(2.675) == Decimal("2.68").
    """
    return _to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def to_weight(value: MoneyLike) -> Decimal:
    """
    Rounds a weight in kilograms half-up to the gram.

    Args:
        value: The weight in kg (None counts as zero).

    Returns:
        A Decimal with exactly three decimal places.
    """
    return _to_decimal(value).quantize(WEIGHT_QUANT, rounding=ROUND_HALF_UP)


def money_to_float(value: MoneyLike) -> float:
    """
    Converts an amount to a float for the legacy DOUBLE columns, after rounding to the paisa.

    Args:
        value: The amount.

    Returns:
        The rounded amount as float.
    """
    return float(to_money(value))


def is_billable_delta(delta: MoneyLike) -> bool:
    """
    True when a delta is at least one paisa in either direction.

    Args:
        delta: The signed delta.

    Returns:
        Whether the delta should move money.
    """
    return abs(to_money(delta)) >= MIN_BILLABLE_DELTA
