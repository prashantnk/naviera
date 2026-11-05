"""
Booking-time pricing rules (DESIGN.md v4 D3; merged WP0 + WP1 items).

- A-02: the flow (B2C / B2B) comes from the booking route (`service_flow`), never from the
  product category; a B2C booking carrying B2B-only fields (COMMERCIAL, PO, blind pickup,
  carrier's risk, appointment, pickup strategy) is refused instead of silently re-priced.
- WP0: TO_PAY and B2B reverse are refused (`mvp_scope`).
- A-26: per-flow weight caps (+ dims > 0 in the schema).
- Q7: Book always re-prices from scratch; when the seller's `expected_total` differs from
  the fresh total the booking answers 409 PRICE_CHANGED with the new total.
- Q6: Delhivery down → stored price ≤ 24 h, else 503 "price unavailable".
- Q9: COD only when the admin set the COD fee; never on Prime.

Spring analogy: a `@Component` of booking validators + a pricing facade used by the
`ShipmentService.createShipment` transaction.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.money import ZERO_MONEY, money_to_float, to_money
from app.models.manifests import ServiceFlow
from app.models.pickups import ProductCategory, ServiceOption, ServiceType
from app.models.tenants import Tenant
from app.schemas.v1.pickups import PickupCreate
from app.services.pricing.delhivery import PriceFreshness
from app.services.pricing.policy import COD_DISABLED_DETAIL, policy_of
from app.services.pricing.quote_service import (
    PRIME_COD_REASON,
    PricedOption,
    QuoteService,
    SellInputs,
    assert_mvp_scope,
    assert_weight_limits,
    build_carrier_cost,
    flow_of_option,
    options_for_flow,
    price_option,
)
from app.services.pricing.sell_price import terms_for
from app.services.pricing.types import ParcelSpec, QuoteUnavailableCode

PRICE_CHANGED_CODE = "PRICE_CHANGED"
PRICE_CHANGED_MESSAGE = (
    "The price changed since you saw it: it is now ₹{new_total}. Please confirm the new price to book."
)
PRICE_UNAVAILABLE_DETAIL = "We couldn't get a price for this shipment right now. Please try again in a few minutes."
COMMERCIAL_IS_B2B_DETAIL = (
    "Commercial goods (for resale) ship as B2B cargo. Book them from B2B › New LR, or pick the "
    "product category that describes the parcel."
)
B2B_FIELDS_ON_B2C_DETAIL = "These fields are only for B2B cargo bookings: {fields}. Remove them or book from B2B › New LR."
OPTION_FLOW_MISMATCH_DETAIL = "{option} is not offered for {flow} shipments."
BLIND_NEEDS_B2B_DETAIL = "Blind pickups (no box details) are only for B2B cargo."
OPTION_SERVICE_TYPES = {
    ServiceOption.DELHIVERY_SURFACE: ServiceType.SURFACE_ROAD,
    ServiceOption.DELHIVERY_EXPRESS: ServiceType.AIR,
    ServiceOption.PRIME_SURFACE: ServiceType.SURFACE_ROAD,
    ServiceOption.DELHIVERY_B2B_SURFACE: ServiceType.SURFACE_ROAD,
}
"""`service_type` is derived from the option (Express = Air where Delhivery can)."""


def b2b_markers(payload: PickupCreate) -> List[str]:
    """The B2B-only fields a booking carries (mirror of the stored B2B classifier)."""
    markers = []
    if payload.po_number and payload.po_number.strip():
        markers.append("PO number")
    if payload.is_blind_pickup:
        markers.append("blind pickup")
    if payload.is_carriers_risk:
        markers.append("carrier's risk")
    if payload.appointment_id is not None:
        markers.append("delivery appointment")
    if payload.pickup_strategy is not None:
        markers.append("pickup strategy")
    return markers


def booking_flow(payload: PickupCreate) -> ServiceFlow:
    """
    The booking's flow: the route's `service_flow`, else the option's flow, else (legacy
    clients) inferred from the B2B fields. The product category never decides it (A-02).
    """
    if payload.service_flow is not None:
        return payload.service_flow
    if payload.service_option is not None:
        return flow_of_option(payload.service_option)
    is_b2b = bool(b2b_markers(payload)) or payload.product_category == ProductCategory.COMMERCIAL
    return ServiceFlow.B2B if is_b2b else ServiceFlow.B2C


def assert_flow_fields(payload: PickupCreate, flow: ServiceFlow) -> None:
    """
    A-02: a B2C booking must not carry B2B-only fields (they would re-classify it as B2B).

    Raises:
        HTTPException(400): plain-English reason.
    """
    if flow != ServiceFlow.B2C:
        return
    if payload.product_category == ProductCategory.COMMERCIAL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, COMMERCIAL_IS_B2B_DETAIL)
    if payload.is_blind_pickup:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BLIND_NEEDS_B2B_DETAIL)
    markers = b2b_markers(payload)
    if markers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, B2B_FIELDS_ON_B2C_DETAIL.format(fields=", ".join(markers)))


def booking_option(payload: PickupCreate, flow: ServiceFlow) -> ServiceOption:
    """
    The option to book: the seller's pick (must belong to the flow), else the flow default
    (B2B → Prime; B2C → Express when `service_type` is AIR, else Surface).

    Raises:
        HTTPException(400): option not offered for the flow.
    """
    allowed = options_for_flow(flow)
    if payload.service_option is not None:
        if payload.service_option not in allowed:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                OPTION_FLOW_MISMATCH_DETAIL.format(option=payload.service_option.value, flow=flow.value),
            )
        return payload.service_option
    if flow == ServiceFlow.B2B:
        return ServiceOption.PRIME_SURFACE
    if payload.service_type == ServiceType.AIR:
        return ServiceOption.DELHIVERY_EXPRESS
    return ServiceOption.DELHIVERY_SURFACE


def service_type_for(option: ServiceOption) -> ServiceType:
    """The legacy `service_type` column value of an option."""
    return OPTION_SERVICE_TYPES[option]


def price_changed_error(expected: Decimal, priced: PricedOption) -> HTTPException:
    """409 PRICE_CHANGED with the fresh total (the client re-confirms with expected_total = new_total)."""
    new_total = money_to_float(priced.sell.total)
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": PRICE_CHANGED_CODE,
            "message": PRICE_CHANGED_MESSAGE.format(new_total=f"{new_total:,.2f}"),
            "expected_total": money_to_float(expected),
            "new_total": new_total,
            "service_option": priced.quote.option.value,
        },
    )


@dataclass(frozen=True)
class BookingPrice:
    """The priced booking: the bill plus the server-only carrier record."""

    flow: ServiceFlow
    option: ServiceOption
    priced: PricedOption
    carrier_cost: Dict[str, Any]


def _cod_goods(payload: PickupCreate) -> Decimal:
    """A-01: the goods COD is exactly what the seller typed (0 when not COD)."""
    payment = payload.payment_details
    return to_money(payment.cod_amount) if payment.is_cod else ZERO_MONEY


def _assert_cod_allowed(payload: PickupCreate, option: ServiceOption, cod_enabled: bool) -> None:
    """Q9: COD needs the admin's COD fee and is never offered on Logismart Prime."""
    if not payload.payment_details.is_cod:
        return
    if option == ServiceOption.PRIME_SURFACE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, PRIME_COD_REASON)
    if not cod_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, COD_DISABLED_DETAIL)


async def price_booking(
    session: AsyncSession,
    tenant: Tenant,
    payload: PickupCreate,
    *,
    pickup_pincode: str,
    delivery_pincode: str,
) -> BookingPrice:
    """
    Validates the booking's flow/option and prices it fresh (Q7).

    Args:
        session: The booking transaction's session (price-cache rows commit with it).
        tenant: The tenant.
        payload: The booking body.
        pickup_pincode: Resolved origin pincode.
        delivery_pincode: Resolved destination pincode.

    Returns:
        The BookingPrice.

    Raises:
        HTTPException: 400 (scope, flow, COD, not serviceable), 409 PRICE_CHANGED, 503 unavailable.
    """
    flow = booking_flow(payload)
    assert_flow_fields(payload, flow)
    assert_mvp_scope(payload.payment_details.freight_payment_mode, payload.shipment_type, flow)
    assert_weight_limits(flow, payload.packages)
    option = booking_option(payload, flow)
    policy = policy_of(tenant)
    _assert_cod_allowed(payload, option, bool(policy and policy.cod_enabled))
    spec = ParcelSpec(
        pickup_pincode=pickup_pincode,
        delivery_pincode=delivery_pincode,
        packages=tuple(payload.packages),
        shipment_type=payload.shipment_type,
        is_blind_pickup=payload.is_blind_pickup,
        estimated_box_count=payload.estimated_box_count,
        door_delivery=payload.door_delivery,
        invoice_value=to_money(payload.payment_details.shipment_total_value),
        carriers_risk=payload.is_carriers_risk,
    )
    is_cod = payload.payment_details.is_cod
    quote = await QuoteService(session).carrier_quote(
        tenant, policy, option, spec, freshness=PriceFreshness.BOOK, include_rto=True, is_cod=is_cod
    )
    if not quote.serviceable:
        if quote.unavailable_code == QuoteUnavailableCode.PRICE_UNAVAILABLE:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, quote.unavailable_reason or PRICE_UNAVAILABLE_DETAIL)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, quote.unavailable_reason or PRICE_UNAVAILABLE_DETAIL)
    terms = terms_for(quote, policy)  # type: ignore[arg-type]  (policy is valid when serviceable)
    sell_inputs = SellInputs(
        mode=payload.payment_details.freight_payment_mode,
        is_cod=is_cod,
        cod_goods=_cod_goods(payload),
        add_shipping_to_cod=payload.payment_details.add_shipping_to_cod and is_cod,
    )
    priced = price_option(quote, terms, spec, sell_inputs)
    expected: Optional[float] = payload.expected_total
    if expected is not None and to_money(expected) != priced.sell.total:
        raise price_changed_error(to_money(expected), priced)
    return BookingPrice(flow=flow, option=option, priced=priced, carrier_cost=build_carrier_cost(quote, spec, terms))
