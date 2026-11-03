"""
Screen ₹ == DB ₹ assertions (proves the Zero Frontend Math rule end to end).

The UI must render exactly the amount the backend stored. These helpers parse
the rupee text inside one `data-testid` element and compare it to the DB value,
rounded half-up to the paisa on both sides. No tolerance: plan §2.0 says money
invariants compare rounded values exactly.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:  # Playwright is only needed when a page is actually read.
    from playwright.async_api import Locator

PAISA = Decimal("0.01")
RUPEE_SYMBOL = "₹"
UNICODE_MINUS = "\u2212"
_MONEY_TEXT_RE = re.compile(r"^\(?-?\d+(\.\d{1,2})?\)?$")

MoneyLike = Union[Decimal, float, int, str]


def to_paisa(value: MoneyLike) -> Decimal:
    """Rounds any money-like value half-up to 2 decimals (`Decimal`, never float math)."""
    return Decimal(str(value)).quantize(PAISA, rounding=ROUND_HALF_UP)


def parse_rupees(text: str) -> Decimal:
    """
    Parses an on-screen rupee amount into `Decimal`.

    Accepts Indian digit grouping and a sign before or after the symbol:
    `"₹1,23,456.50"`, `"-₹159.85"`, `"₹ -159.85"`, `"−₹2.00"`, `"(₹10.00)"`.
    Parentheses mean negative (accounting style).

    Raises:
        ValueError: When the text is not a single rupee amount.
    """
    cleaned = (
        text.strip()
        .replace(UNICODE_MINUS, "-")
        .replace(RUPEE_SYMBOL, "")
        .replace(",", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    unbalanced = cleaned.startswith("(") != cleaned.endswith(")")
    if unbalanced or cleaned.startswith("(-") or not _MONEY_TEXT_RE.match(cleaned):
        raise ValueError(f"Not a single rupee amount: {text!r}")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    digits = cleaned.strip("()")
    try:
        amount = Decimal(digits)
    except InvalidOperation as exc:  # pragma: no cover - regex already guards this
        raise ValueError(f"Not a rupee amount: {text!r}") from exc
    return to_paisa(-amount if negative else amount)


async def screen_rupees(locator: "Locator") -> Decimal:
    """Reads the visible text of one money element and parses it."""
    return parse_rupees(await locator.inner_text())


async def assert_screen_money_equals_db(
    locator: "Locator", db_value: MoneyLike, label: str = "amount"
) -> Decimal:
    """
    Asserts the rupee value shown in `locator` equals `db_value` to the paisa.

    Returns:
        The parsed screen value.

    Raises:
        AssertionError: With both values when they differ.
    """
    shown = await screen_rupees(locator)
    expected = to_paisa(db_value)
    assert shown == expected, f"{label}: screen shows ₹{shown} but DB has ₹{expected}"
    return shown
