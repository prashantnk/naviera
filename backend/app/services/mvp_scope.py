"""
MVP scope switches (user decisions of 2026-10-30, fix plan WP0).

- TO_PAY ("Freight on Delivery") bookings are OFF for the MVP: new bookings, edits and
  re-price previews that switch to TO_PAY are refused with a clear 400. Existing TO_PAY
  rows stay readable and keep re-pricing normally.
- B2B reverse LRs are OFF for the MVP (B2C reverse pickups stay available).

Re-enabling either is a one-line change here. The flags are module attributes read at
call time, so the in-process golden suites can `monkeypatch` them to seed legacy rows
through the real booking path.

Spring analogy: a tiny `@ConfigurationProperties`-style feature-flag holder.
"""

from app.models.pickups import FreightPaymentMode, ShipmentType

TO_PAY_BOOKINGS_ENABLED = False
"""False → `FreightPaymentMode.TO_PAY` cannot be chosen on a booking or an edit."""
B2B_REVERSE_BOOKINGS_ENABLED = False
"""False → B2B (cargo) shipments cannot be booked as REVERSE."""

TO_PAY_DISABLED_DETAIL = (
    "Freight on Delivery (To Pay) is not available yet. Choose Prepaid so the shipping "
    "charge is paid from your wallet."
)
B2B_REVERSE_DISABLED_DETAIL = (
    "B2B reverse (return) LRs are not available yet. Please contact Logismart support to "
    "arrange a return pickup."
)


def is_to_pay_blocked(mode: FreightPaymentMode) -> bool:
    """True when `mode` is TO_PAY and TO_PAY bookings are switched off."""
    return mode == FreightPaymentMode.TO_PAY and not TO_PAY_BOOKINGS_ENABLED


def is_b2b_reverse_blocked(shipment_type: ShipmentType, is_b2b: bool) -> bool:
    """True when a B2B shipment is booked as REVERSE while that is switched off."""
    return is_b2b and shipment_type == ShipmentType.REVERSE and not B2B_REVERSE_BOOKINGS_ENABLED
