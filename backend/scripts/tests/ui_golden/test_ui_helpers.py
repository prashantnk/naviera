"""
Pure unit tests of the UI-layer helpers (no browser, no DB, no network).

They run even without the `e2e` dev group installed.
"""

from decimal import Decimal

import pytest

from .hud import format_step_label
from .money import parse_rupees, to_paisa
from .testids import BookingIds, PickupDispatchIds, testid


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("₹1,234.50", Decimal("1234.50")),
        ("₹1,23,456.5", Decimal("123456.50")),
        ("₹0.00", Decimal("0.00")),
        ("-₹159.85", Decimal("-159.85")),
        ("₹ -159.85", Decimal("-159.85")),
        ("\u2212₹2.00", Decimal("-2.00")),
        ("(₹10.00)", Decimal("-10.00")),
        ("  ₹\u00a0206.50 ", Decimal("206.50")),
        ("₹75000", Decimal("75000.00")),
    ],
)
def test_parse_rupees_accepts_indian_formats(text: str, expected: Decimal) -> None:
    """Indian grouping, sign placement, unicode minus and accounting brackets all parse."""
    assert parse_rupees(text) == expected


@pytest.mark.parametrize(
    "text", ["", "₹", "Total ₹10", "₹1.234", "₹10.00 + GST", "(₹10.00", "₹1,2a3", "(-₹5)"]
)
def test_parse_rupees_rejects_non_amounts(text: str) -> None:
    """Text that is not exactly one amount is rejected rather than guessed."""
    with pytest.raises(ValueError):
        parse_rupees(text)


def test_to_paisa_rounds_half_up() -> None:
    """Money rounds half-up to the paisa (never banker's rounding)."""
    assert to_paisa("2.005") == Decimal("2.01")
    assert to_paisa(2.675) == Decimal("2.68")
    assert to_paisa(-1.005) == Decimal("-1.01")


def test_format_step_label() -> None:
    """Banner text follows `<J> step <n>/<total>: <text>`."""
    assert format_step_label("J09", 3, 7, "Book shipment") == "J09 step 3/7: Book shipment"
    assert format_step_label("SMOKE", 1, 1, "") == "SMOKE step 1/1"
    with pytest.raises(ValueError):
        format_step_label("J09", 8, 7, "x")
    with pytest.raises(ValueError):
        format_step_label("J09", 0, 7, "x")


def test_testid_convention() -> None:
    """Static parts are lowercase kebab-case; dynamic ids keep their exact casing."""
    assert testid("wallet", "header", "balance") == "wallet.header.balance"
    assert (
        PickupDispatchIds.actual_pieces("LOGISMART-TEST-AB12CD34")
        == "pickup-dispatch.row.LOGISMART-TEST-AB12CD34.actual-pieces"
    )
    assert BookingIds.package_field(0, "weight") == "booking.package.weight-0"
    assert BookingIds.quote_card("SURFACE_ROAD") == "booking.quote.card-surface-road"
    for bad in (("Wallet", "header", "balance"), ("wallet", "balance"), ("wallet", "", "x")):
        with pytest.raises(ValueError):
            testid(*bad)


def test_resolve_chrome_path_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """`UI_CHROME_PATH` wins, then the real Chrome binary, then Chrome/Chromium on PATH."""
    browser_session = pytest.importorskip("scripts.tests.ui_golden.browser_session")
    monkeypatch.setattr(browser_session.shutil, "which", lambda name: f"/usr/bin/{name}")

    monkeypatch.setenv(browser_session.CHROME_PATH_ENV_VAR, "/custom/chrome")
    assert browser_session.resolve_chrome_path() == "/custom/chrome"

    monkeypatch.delenv(browser_session.CHROME_PATH_ENV_VAR)
    monkeypatch.setattr(browser_session.os.path, "isfile", lambda path: True)
    assert browser_session.resolve_chrome_path() == browser_session.DEFAULT_CHROME_PATH

    monkeypatch.setattr(browser_session.os.path, "isfile", lambda path: False)
    assert browser_session.resolve_chrome_path() == "/usr/bin/google-chrome"

    monkeypatch.setattr(browser_session.shutil, "which", lambda name: None)
    assert browser_session.resolve_chrome_path() == browser_session.DEFAULT_CHROME_PATH
