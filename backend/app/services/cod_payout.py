"""
COD and door-collection rules: how much cash the rider collects at the door, and how
much of it belongs to the merchant (plan item B7, hard block H-9).

One model for every caller (booking, RepricingService, settle-cod, remittance batch,
integrity audit):

- `cod_amount` is the COD the consignee pays for the goods, plus, for PREPAID/POSTPAID
  orders with `add_shipping_to_cod`, the shipping charge (the merchant already paid the
  freight from the wallet and is reimbursed in full, decision D26).
- `freight_collectible` is TO_PAY ("Freight on Delivery") freight still due from the
  consignee. For TO_PAY the freight never sits inside `cod_amount`, so the door total
  `cod_amount + freight_collectible` never counts it twice, a TO_PAY order switched from
  COD to prepaid keeps its freight, and a Freight Collection paid by the merchant lowers
  exactly one column.
- Once Delivered (COMPLETED) both columns are frozen: the cash is already collected (H-9).

Legacy rows (booked before `pricing_breakdown.billing_channel` existed) stored TO_PAY +
COD freight inside `cod_amount`; the readers below keep today's subtraction for them.

Spring Boot analogy: a stateless `@Component` policy bean shared by several services.
"""

from decimal import Decimal
from typing import Optional, Tuple

from app.core.money import ZERO_MONEY, money_to_float, to_money
from app.models.pickups import (
    FreightPaymentMode,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
)

BILLING_CHANNEL_BREAKDOWN_KEY = "billing_channel"
"""Booking-time marker in `pricing_breakdown` (same key as `services.repricing.BILLING_CHANNEL_KEY`).
Its presence tells a row booked under the B7 model apart from a legacy row."""

COLLECTIBLE_FROZEN_STATUSES = frozenset({PickupStatus.COMPLETED})
"""H-9: statuses after which the door collectible can no longer change (wave 2 adds RTO_DELIVERED)."""


def _is_legacy_row(payment: PaymentDetails) -> bool:
    """True for rows booked before the B7 model (no `billing_channel` marker in the breakdown)."""
    return BILLING_CHANNEL_BREAKDOWN_KEY not in (payment.pricing_breakdown or {})


def _freight_inside_cod(payment: PaymentDetails) -> bool:
    """
    True when the stored `cod_amount` already includes the shipping charge.

    PREPAID/POSTPAID + `add_shipping_to_cod` always; TO_PAY + `add_shipping_to_cod` only on
    legacy rows (new TO_PAY rows keep the freight in `freight_collectible`).
    """
    if not (payment.is_cod and payment.add_shipping_to_cod):
        return False
    if payment.freight_payment_mode == FreightPaymentMode.TO_PAY:
        return _is_legacy_row(payment)
    return True


def cod_goods_amount(payment: Optional[PaymentDetails]) -> Decimal:
    """
    Goods part of the COD read from the stored row (the COD-fee base, fixes R1).

    Callers re-pricing a shipment must read this BEFORE they change the total.

    Args:
        payment: The shipment's payment details (None for legacy rows).

    Returns:
        cod_amount minus the shipping charge it contains, never negative; 0 when not COD.
    """
    if payment is None or not payment.is_cod:
        return ZERO_MONEY
    goods = to_money(payment.cod_amount)
    if _freight_inside_cod(payment):
        goods -= to_money(payment.total_logistics_cost)
    return max(goods, ZERO_MONEY)


def collectible_amounts(
    *,
    is_cod: bool,
    goods: Decimal,
    total: Decimal,
    mode: FreightPaymentMode,
    add_shipping_to_cod: bool,
    merchant_paid: Decimal,
) -> Tuple[Decimal, Decimal]:
    """
    The two door-collection columns for a (re-)priced shipment.

    Args:
        is_cod: Whether the consignee pays for the goods at the door.
        goods: Goods COD (see `cod_goods_amount`, or the booking's COD for new rows).
        total: The bill (`total_logistics_cost`, GST included).
        mode: Freight payment mode.
        add_shipping_to_cod: Whether the shipping charge is collected with the COD.
        merchant_paid: TO_PAY freight the merchant already paid (Σ FREIGHT_COLLECTION).

    Returns:
        `(cod_amount, freight_collectible)`, each rounded to the paisa.
    """
    goods_cod = to_money(goods) if is_cod else ZERO_MONEY
    bill = to_money(total)
    if mode == FreightPaymentMode.TO_PAY:
        return goods_cod, max(bill - to_money(merchant_paid), ZERO_MONEY)
    if is_cod and add_shipping_to_cod:
        return to_money(goods_cod + bill), ZERO_MONEY
    return goods_cod, ZERO_MONEY


def is_collectible_frozen(shipment: PickupRequest) -> bool:
    """H-9: True once the shipment is Delivered, so COD / freight to collect must not change."""
    return shipment.status in COLLECTIBLE_FROZEN_STATUSES


def door_collectible(payment: Optional[PaymentDetails]) -> Decimal:
    """
    Cash the rider collects at the door: COD (if any) plus TO_PAY freight still due.

    Args:
        payment: The shipment's payment details.

    Returns:
        The door total, rounded to the paisa.
    """
    if payment is None:
        return ZERO_MONEY
    cod = to_money(payment.cod_amount) if payment.is_cod else ZERO_MONEY
    return to_money(cod + to_money(payment.freight_collectible))


def carrier_freight_collected(payment: Optional[PaymentDetails]) -> float:
    """
    TO_PAY freight the carrier collects at the door (kept by Logismart, never paid out).

    Args:
        payment: The shipment's payment details.

    Returns:
        The carrier's share of the door cash, rounded to paise.
    """
    if payment is None or payment.freight_payment_mode != FreightPaymentMode.TO_PAY:
        return 0.0
    if _freight_inside_cod(payment):
        return money_to_float(payment.total_logistics_cost)
    return money_to_float(payment.freight_collectible)


def cod_payout_amount(payment: Optional[PaymentDetails]) -> float:
    """
    Merchant's share of the COD cash collected for one shipment (decision D26).

    PREPAID/POSTPAID: the whole `cod_amount` (shipping included when added to COD, since
    the merchant already paid it from the wallet). TO_PAY: the goods only.

    Args:
        payment: The shipment's payment details (may be None for legacy rows).

    Returns:
        The amount to credit / remit to the merchant, never negative, rounded to paise.
    """
    if payment is None or not payment.is_cod:
        return 0.0
    if payment.freight_payment_mode == FreightPaymentMode.TO_PAY:
        return money_to_float(cod_goods_amount(payment))
    return money_to_float(payment.cod_amount)
