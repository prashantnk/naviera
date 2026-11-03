"""
QuoteService: option cards for the rate calculator / booking, and the price the booking
and re-pricing paths write (DESIGN.md v4 §A, §C.3).

Flow per option: provider (Delhivery client + cache, or the Prime rate table) gives the
carrier cost → `sell_price` turns it into the seller's bill → the result carries the
customer `pricing_breakdown` and the server-only `carrier_cost` record.

Spring analogy: an orchestrating `@Service` that delegates to `@Component` strategies
(one per carrier) and maps the results onto DTOs.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.money import ZERO_MONEY, money_to_float, to_money, to_weight
from app.models.manifests import ServiceFlow
from app.models.pickups import FreightPaymentMode, ServiceOption, ShipmentType
from app.models.tenants import Tenant
from app.schemas.v1.pickups import (
    EWAY_BILL_MANDATORY_THRESHOLD,
    PackageCreate,
    declared_total_value,
)
from app.schemas.v1.pricing import (
    PricingPolicy,
    QuoteOption,
    QuoteRequest,
    QuoteResponse,
    SellLine,
    ValuationResponse,
)
from app.services import mvp_scope
from app.services.pricing import weights
from app.services.pricing.delhivery import (
    SS_FORWARD,
    SS_REVERSE,
    DelhiveryProvider,
    PriceFreshness,
    price_params,
)
from app.services.pricing.delhivery_b2b import DelhiveryB2BProvider, estimate_body
from app.services.pricing.policy import (
    COD_DISABLED_REASON,
    POLICY_INVALID_REASON,
    policy_of,
)
from app.services.pricing.prime import PrimeProvider
from app.services.pricing.sell_price import (
    BreakdownContext,
    SellPrice,
    SellTerms,
    compute_sell,
    customer_breakdown,
    door_and_remittance,
    terms_for,
)
from app.services.pricing.types import (
    CarrierLeg,
    CarrierLegKind,
    CarrierQuote,
    CostLine,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)

logger = logging.getLogger(__name__)

CARRIER_COST_VERSION = 1
B2C_OPTIONS: Tuple[ServiceOption, ...] = (ServiceOption.DELHIVERY_SURFACE, ServiceOption.DELHIVERY_EXPRESS)
B2B_OPTIONS: Tuple[ServiceOption, ...] = (ServiceOption.PRIME_SURFACE, ServiceOption.DELHIVERY_B2B_SURFACE)
FLOW_OPTIONS = {ServiceFlow.B2C: B2C_OPTIONS, ServiceFlow.B2B: B2B_OPTIONS}
IST = timezone(timedelta(hours=5, minutes=30))

B2C_MAX_BOX_WEIGHT_KG = Decimal("50")
B2C_HEAVY_WARNING_KG = Decimal("20")
B2B_MAX_BOX_WEIGHT_KG = Decimal("2000")
B2B_MAX_TOTAL_WEIGHT_KG = Decimal("20000")
B2B_HEAVY_WARNING_KG = Decimal("1000")
"""A-26 per-flow caps (hard 400) and the 'unusually heavy' confirm threshold (total kg)."""
B2C_BOX_TOO_HEAVY = "A parcel box can weigh at most {limit} kg. Check the weight (kg, not grams) or book it as B2B cargo."
B2B_BOX_TOO_HEAVY = "A cargo box can weigh at most {limit} kg. Please check the weight."
B2B_TOTAL_TOO_HEAVY = "One LR can carry at most {limit} kg. Split the consignment into several LRs."
OPTION_DISABLED_REASON = "This service is switched off by Logismart for now."
WRONG_FLOW_REASON = "This service is not offered for this kind of shipment."
PRIME_COD_REASON = "Cash on Delivery is not available for Logismart Prime (B2B cargo)."
B2B_COD_REASON = "Cash on Delivery is not available for B2B cargo bookings yet. Book this LR as Prepaid."
BLIND_NOT_B2C = "Blind pickups (no box details) are only for B2B cargo."


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- pure helpers -------------------------------------------------------------------


def options_for_flow(flow: ServiceFlow) -> Tuple[ServiceOption, ...]:
    """The options a flow can offer (B2C → Delhivery Surface/Express; B2B → Prime + Delhivery B2B Cargo)."""
    return FLOW_OPTIONS[flow]


def flow_of_option(option: ServiceOption) -> ServiceFlow:
    """The flow an option belongs to."""
    return ServiceFlow.B2B if option in B2B_OPTIONS else ServiceFlow.B2C


def valuation(shipment_value: float, shipment_tax_value: float) -> ValuationResponse:
    """D-06: the server-computed declared total and whether it needs an e-way bill."""
    total = declared_total_value(shipment_value, shipment_tax_value)
    return ValuationResponse(
        shipment_total_value=total,
        eway_bill_required=total >= EWAY_BILL_MANDATORY_THRESHOLD,
        eway_bill_threshold=float(EWAY_BILL_MANDATORY_THRESHOLD),
    )


def assert_weight_limits(flow: ServiceFlow, packages: Sequence[PackageCreate]) -> None:
    """
    A-26 hard caps per flow (a 500 kg typo for 5 kg must not book).

    Raises:
        HTTPException(400): a box or the LR is over the cap.
    """
    heaviest = weights.max_box_weight_kg(packages)
    if flow == ServiceFlow.B2C and heaviest > B2C_MAX_BOX_WEIGHT_KG:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, B2C_BOX_TOO_HEAVY.format(limit=B2C_MAX_BOX_WEIGHT_KG))
    if flow == ServiceFlow.B2B and heaviest > B2B_MAX_BOX_WEIGHT_KG:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, B2B_BOX_TOO_HEAVY.format(limit=B2B_MAX_BOX_WEIGHT_KG))
    if flow == ServiceFlow.B2B and weights.total_actual_kg(packages) > B2B_MAX_TOTAL_WEIGHT_KG:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, B2B_TOTAL_TOO_HEAVY.format(limit=B2B_MAX_TOTAL_WEIGHT_KG)
        )


def heavy_threshold(flow: ServiceFlow) -> Decimal:
    """Total kg above which the UI asks 'is this weight right?'."""
    return B2B_HEAVY_WARNING_KG if flow == ServiceFlow.B2B else B2C_HEAVY_WARNING_KG


def assert_mvp_scope(mode: FreightPaymentMode, shipment_type: ShipmentType, flow: ServiceFlow) -> None:
    """
    WP0 switches (TO_PAY off, B2B reverse off) — shared by quotes and bookings.

    Raises:
        HTTPException(400): with `mvp_scope.*_DISABLED_DETAIL`.
    """
    if mvp_scope.is_to_pay_blocked(mode):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, mvp_scope.TO_PAY_DISABLED_DETAIL)
    if mvp_scope.is_b2b_reverse_blocked(shipment_type, flow == ServiceFlow.B2B):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, mvp_scope.B2B_REVERSE_DISABLED_DETAIL)


def delhivery_provider_for(
    session: AsyncSession, tenant: Tenant, option: ServiceOption
) -> "DelhiveryProvider | DelhiveryB2BProvider":
    """The Delhivery provider of an option: the B2B (LTL) estimate API or the B2C price API."""
    if option == ServiceOption.DELHIVERY_B2B_SURFACE:
        return DelhiveryB2BProvider(session, tenant)
    return DelhiveryProvider(session, tenant)


def expected_delivery(transit_days: Optional[int], start: Optional[date] = None) -> Optional[date]:
    """Expected delivery date (IST calendar) = start (default today) + transit days."""
    if transit_days is None:
        return None
    base = start or datetime.now(IST).date()
    return base + timedelta(days=int(transit_days))


# --- carrier_cost (server-only JSON) -------------------------------------------------


def _decimal(value: Any) -> Decimal:
    """A stored JSON number/string as Decimal."""
    return Decimal(str(value if value is not None else 0))


def leg_to_json(leg: Optional[CarrierLeg]) -> Optional[Dict[str, Any]]:
    """JSON-safe form of a carrier leg (Decimals as strings)."""
    if leg is None:
        return None
    return {
        "kind": leg.kind.value,
        "cost": str(leg.cost),
        "lines": [{"code": c.code, "label": c.label, "amount": str(c.amount)} for c in leg.lines],
        "charged_weight_kg": str(leg.charged_weight_kg),
        "transit_days": leg.transit_days,
        "source": leg.source.value,
        "fetched_at": leg.fetched_at.isoformat(),
        "details": dict(leg.details),
    }


def leg_from_json(raw: Optional[Mapping[str, Any]]) -> Optional[CarrierLeg]:
    """Inverse of `leg_to_json` (None stays None)."""
    if not raw:
        return None
    return CarrierLeg(
        kind=CarrierLegKind(raw["kind"]),
        cost=to_money(_decimal(raw.get("cost"))),
        lines=tuple(
            CostLine(code=line["code"], label=line["label"], amount=to_money(_decimal(line["amount"])))
            for line in raw.get("lines") or []
        ),
        charged_weight_kg=to_weight(_decimal(raw.get("charged_weight_kg"))),
        transit_days=raw.get("transit_days"),
        source=PriceSource(raw.get("source") or PriceSource.LIVE.value),
        fetched_at=datetime.fromisoformat(raw["fetched_at"]) if raw.get("fetched_at") else _utc_now_naive(),
        details=dict(raw.get("details") or {}),
    )


def spec_to_json(spec: ParcelSpec) -> Dict[str, Any]:
    """The pricing inputs as stored in `carrier_cost["inputs"]`."""
    return {
        "pickup_pincode": spec.pickup_pincode,
        "delivery_pincode": spec.delivery_pincode,
        "shipment_type": spec.shipment_type.value,
        "is_blind_pickup": spec.is_blind_pickup,
        "estimated_box_count": spec.estimated_box_count,
        "door_delivery": spec.door_delivery,
        "invoice_value": str(spec.invoice_value),
        "carriers_risk": spec.carriers_risk,
        "packages": [p.model_dump(mode="json") for p in spec.packages],
    }


def spec_from_json(raw: Mapping[str, Any]) -> ParcelSpec:
    """Inverse of `spec_to_json` (the booked inputs of a stored carrier record)."""
    return ParcelSpec(
        pickup_pincode=str(raw.get("pickup_pincode") or ""),
        delivery_pincode=str(raw.get("delivery_pincode") or ""),
        packages=tuple(PackageCreate(**p) for p in raw.get("packages") or []),
        shipment_type=ShipmentType(raw.get("shipment_type") or ShipmentType.FORWARD.value),
        is_blind_pickup=bool(raw.get("is_blind_pickup")),
        estimated_box_count=raw.get("estimated_box_count"),
        door_delivery=bool(raw.get("door_delivery")),
        invoice_value=to_money(_decimal(raw.get("invoice_value"))),
        carriers_risk=bool(raw.get("carriers_risk")),
    )


def build_carrier_cost(
    quote: CarrierQuote,
    spec: ParcelSpec,
    terms: SellTerms,
    carrier_billed: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The server-only `payment_details.carrier_cost` record (booking and every re-price)."""
    return {
        "version": CARRIER_COST_VERSION,
        "option": quote.option.value,
        "inputs": spec_to_json(spec),
        "forward": leg_to_json(quote.forward),
        "rto": leg_to_json(quote.rto),
        "snapshot": dict(quote.snapshot),
        "terms": terms.to_json(),
        "carrier_billed": dict(carrier_billed) if carrier_billed else None,
    }


def provisional_rto(forward: CarrierLeg) -> CarrierLeg:
    """
    RTO leg billed at the forward cost when no RTO price was stored (Delhivery was down at
    booking); flagged for ops (DESIGN §A "Money paths").
    """
    return CarrierLeg(
        kind=CarrierLegKind.RTO,
        cost=forward.cost,
        lines=(),
        charged_weight_kg=forward.charged_weight_kg,
        transit_days=None,
        source=PriceSource.PROVISIONAL,
        fetched_at=_utc_now_naive(),
        details={"provisional": True},
    )


# --- priced option --------------------------------------------------------------------


@dataclass(frozen=True)
class PricedOption:
    """A serviceable option priced for a seller: bill, breakdown and carrier record."""

    quote: CarrierQuote
    terms: SellTerms
    sell: SellPrice
    breakdown: Dict[str, Any]
    chargeable_weight_kg: Decimal
    transit_days: Optional[int]
    priced_from_cache: bool
    door_collectible: Decimal
    cod_remittance: Decimal


@dataclass(frozen=True)
class SellInputs:
    """The seller-side inputs that change the bill (not the carrier cost)."""

    mode: FreightPaymentMode = FreightPaymentMode.PREPAID
    is_cod: bool = False
    cod_goods: Decimal = ZERO_MONEY
    add_shipping_to_cod: bool = False
    include_rto: bool = False
    charge_cod_fee: bool = True


def volumetric_divisor_for(quote: CarrierQuote) -> Decimal:
    """Volumetric divisor used for the breakdown weight (Prime lane divisor or Delhivery 5000)."""
    raw = quote.snapshot.get("volumetric_divisor") if quote.snapshot else None
    return _decimal(raw) if raw else weights.DELHIVERY_VOLUMETRIC_DIVISOR


def price_option(
    quote: CarrierQuote, terms: SellTerms, spec: ParcelSpec, sell_inputs: SellInputs
) -> PricedOption:
    """
    Turns a serviceable carrier quote into the seller's bill.

    Args:
        quote: Serviceable carrier quote (forward leg present).
        terms: Selling terms (current policy at booking, frozen ones on re-price).
        spec: The parcel (breakdown weights).
        sell_inputs: Payment mode, COD, RTO billing.

    Returns:
        The PricedOption.
    """
    forward = quote.forward
    assert forward is not None, "price_option needs a serviceable quote"
    sell = compute_sell(
        quote.option,
        forward,
        quote.rto,
        terms,
        cod_goods=sell_inputs.cod_goods if sell_inputs.is_cod else ZERO_MONEY,
        include_rto=sell_inputs.include_rto,
        charge_cod_fee=sell_inputs.charge_cod_fee,
    )
    priced_from_cache = forward.source == PriceSource.CACHED
    ctx = BreakdownContext(
        option=quote.option,
        leg=forward.kind.value,
        transit_days=forward.transit_days,
        priced_from_cache=priced_from_cache,
        actual_weight_kg=weights.total_actual_kg(spec.packages),
        volumetric_weight_kg=weights.volumetric_kg(spec.packages, volumetric_divisor_for(quote)),
        chargeable_weight_kg=forward.charged_weight_kg,
        mode=sell_inputs.mode,
        is_cod=sell_inputs.is_cod,
        cod_goods=sell_inputs.cod_goods,
        add_shipping_to_cod=sell_inputs.add_shipping_to_cod,
    )
    door, remittance = door_and_remittance(
        total=sell.total,
        mode=sell_inputs.mode,
        is_cod=sell_inputs.is_cod,
        cod_goods=sell_inputs.cod_goods,
        add_shipping_to_cod=sell_inputs.add_shipping_to_cod,
    )
    return PricedOption(
        quote=quote,
        terms=terms,
        sell=sell,
        breakdown=customer_breakdown(sell, ctx),
        chargeable_weight_kg=forward.charged_weight_kg,
        transit_days=forward.transit_days,
        priced_from_cache=priced_from_cache,
        door_collectible=door,
        cod_remittance=remittance,
    )


def _price_age_minutes(leg: CarrierLeg) -> int:
    """Minutes since the carrier price was obtained."""
    return max(0, int((_utc_now_naive() - leg.fetched_at).total_seconds() // 60))


def option_card(priced: Optional[PricedOption], quote: CarrierQuote) -> QuoteOption:
    """The API option card (greyed out when `priced` is None)."""
    if priced is None:
        return QuoteOption(
            service_option=quote.option,
            serviceable=False,
            unavailable_code=quote.unavailable_code,
            unavailable_reason=quote.unavailable_reason,
        )
    forward = priced.quote.forward
    return QuoteOption(
        service_option=quote.option,
        serviceable=True,
        total_amount=money_to_float(priced.sell.total),
        freight_amount=money_to_float(priced.sell.forward_freight),
        cod_fee=money_to_float(priced.sell.cod_fee),
        tax_amount=money_to_float(priced.sell.gst),
        chargeable_weight_kg=float(priced.chargeable_weight_kg),
        transit_days=priced.transit_days,
        expected_delivery_date=expected_delivery(priced.transit_days),
        sell_lines=[SellLine(**line.to_json()) for line in priced.sell.lines],
        door_collectible_amount=money_to_float(priced.door_collectible),
        cod_remittance_amount=money_to_float(priced.cod_remittance),
        priced_from_cache=priced.priced_from_cache,
        price_age_minutes=_price_age_minutes(forward) if forward is not None and priced.priced_from_cache else None,
    )


# --- service ----------------------------------------------------------------------------


class QuoteService:
    """Carrier quotes + sell prices for one request (session-scoped)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.prime = PrimeProvider(session)

    async def carrier_quote(
        self,
        tenant: Tenant,
        policy: Optional[PricingPolicy],
        option: ServiceOption,
        spec: ParcelSpec,
        *,
        freshness: PriceFreshness,
        include_rto: bool,
        is_cod: bool,
    ) -> CarrierQuote:
        """
        The carrier answer for one option, after the policy gates (invalid policy, option off).

        Returns:
            A serviceable or greyed-out CarrierQuote.
        """
        if policy is None:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.OPTION_DISABLED, POLICY_INVALID_REASON)
        if option not in policy.enabled_options:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.OPTION_DISABLED, OPTION_DISABLED_REASON)
        if option == ServiceOption.PRIME_SURFACE:
            if is_cod:
                return CarrierQuote.unavailable(option, QuoteUnavailableCode.COD_NOT_AVAILABLE, PRIME_COD_REASON)
            return await self.prime.quote(tenant.id, spec)
        if option == ServiceOption.DELHIVERY_B2B_SURFACE and is_cod:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.COD_NOT_AVAILABLE, B2B_COD_REASON)
        return await delhivery_provider_for(self.session, tenant, option).quote(
            option, spec, freshness=freshness, include_rto=include_rto, is_cod=is_cod
        )

    async def quote_options(self, tenant: Tenant, request: QuoteRequest) -> QuoteResponse:
        """
        `POST /quotes`: every option of the flow, priced on the exact booking inputs (A-03).

        Raises:
            HTTPException(400): TO_PAY / B2B reverse (WP0), weight caps (A-26), blind B2C.
        """
        flow = request.service_flow
        assert_mvp_scope(request.freight_payment_mode, request.shipment_type, flow)
        if request.is_blind_pickup and flow == ServiceFlow.B2C:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, BLIND_NOT_B2C)
        assert_weight_limits(flow, request.packages)
        policy = policy_of(tenant)
        cod_available, cod_reason = self._cod_availability(flow, policy)
        total_value = valuation(request.shipment_value, request.shipment_tax_value)
        spec = ParcelSpec(
            pickup_pincode=request.pickup_pincode,
            delivery_pincode=request.delivery_pincode,
            packages=tuple(request.packages),
            shipment_type=request.shipment_type,
            is_blind_pickup=request.is_blind_pickup,
            estimated_box_count=request.estimated_box_count,
            door_delivery=request.door_delivery,
            invoice_value=to_money(total_value.shipment_total_value),
            carriers_risk=request.is_carriers_risk,
        )
        is_cod = request.is_cod and cod_available
        sell_inputs = SellInputs(
            mode=request.freight_payment_mode,
            is_cod=is_cod,
            cod_goods=to_money(request.cod_amount) if is_cod else ZERO_MONEY,
            add_shipping_to_cod=request.add_shipping_to_cod and is_cod,
        )
        cards: List[QuoteOption] = []
        for option in options_for_flow(flow):
            quote = await self.carrier_quote(
                tenant, policy, option, spec, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=is_cod
            )
            priced = price_option(quote, terms_for(quote, policy), spec, sell_inputs) if quote.serviceable else None
            cards.append(option_card(priced, quote))
        await self.session.commit()  # persist fresh Delhivery answers in the price cache
        threshold = heavy_threshold(flow)
        return QuoteResponse(
            shipment_total_value=total_value.shipment_total_value,
            eway_bill_required=total_value.eway_bill_required,
            eway_bill_threshold=total_value.eway_bill_threshold,
            cod_available=cod_available,
            cod_unavailable_reason=cod_reason,
            heavy_weight_warning=weights.total_actual_kg(request.packages) >= threshold,
            heavy_weight_threshold_kg=float(threshold),
            options=cards,
        )

    @staticmethod
    def _cod_availability(flow: ServiceFlow, policy: Optional[PricingPolicy]) -> Tuple[bool, Optional[str]]:
        """(COD can be booked, plain-English reason when not)."""
        if flow == ServiceFlow.B2B:
            return False, B2B_COD_REASON
        if policy is None or not policy.cod_enabled:
            return False, COD_DISABLED_REASON
        return True, None

    # --- re-pricing (D4: RepricingService's only price source) --------------------------

    async def requote(
        self, tenant: Tenant, carrier_cost: Optional[Mapping[str, Any]], request: "RequoteRequest"
    ) -> "PriceResult":
        """
        The new bill of an already booked shipment.

        - Stored carrier record for the same option → frozen terms; no Delhivery call unless a
          carrier input changed (pins / weight slab / leg); then a drift-neutral pair
          `booked + (API(new) − API(booked inputs))` per leg; Prime re-prices from the frozen lane.
        - No record (booked before the redesign) or an option switch → priced fresh under
          the current policy.
        - RTO billed without a stored RTO price → provisional RTO = forward cost (flagged).

        Returns:
            A PriceResult (unserviceable with a reason when it cannot be priced; H-7).
        """
        record = carrier_cost if carrier_cost and carrier_cost.get("option") == request.option.value else None
        if record is None or _prime_lane_changed(record, request):
            return await self._requote_fresh(tenant, request, carrier_cost)
        terms = SellTerms.from_json(record.get("terms") or {})
        quote = await self._requote_from_record(tenant, record, request)
        if not quote.serviceable:
            return PriceResult.unserviceable(quote.unavailable_reason)
        return PriceResult.of(price_option(quote, terms, request.spec, request.sell), request.spec, terms, record)

    async def _requote_fresh(
        self, tenant: Tenant, request: "RequoteRequest", previous: Optional[Mapping[str, Any]]
    ) -> "PriceResult":
        """Legacy rows / option switches: a fresh carrier quote under the current policy."""
        policy = policy_of(tenant)
        quote = await self.carrier_quote(
            tenant,
            policy,
            request.option,
            request.spec,
            freshness=PriceFreshness.BOOK,
            include_rto=request.sell.include_rto,
            is_cod=request.sell.is_cod,
        )
        if not quote.serviceable:
            return PriceResult.unserviceable(quote.unavailable_reason)
        quote = _with_rto_if_billed(quote, request.sell.include_rto)
        terms = terms_for(quote, policy)  # type: ignore[arg-type]  (policy valid when serviceable)
        return PriceResult.of(price_option(quote, terms, request.spec, request.sell), request.spec, terms, previous)

    async def _requote_from_record(
        self, tenant: Tenant, record: Mapping[str, Any], request: "RequoteRequest"
    ) -> CarrierQuote:
        """Re-prices from the booked carrier record (frozen lane / drift-neutral Delhivery)."""
        option = request.option
        if option == ServiceOption.PRIME_SURFACE:
            quote = self.prime.requote(record.get("snapshot") or {}, request.spec)
            return _with_rto_if_billed(quote, request.sell.include_rto) if quote.serviceable else quote
        forward = leg_from_json(record.get("forward"))
        rto = leg_from_json(record.get("rto"))
        booked = spec_from_json(record.get("inputs") or {})
        if forward is None:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.PRICE_UNAVAILABLE, REPRICE_UNAVAILABLE_REASON)
        if not _delhivery_inputs_changed(option, booked, request.spec):
            new_forward, new_rto = forward, rto
        else:
            provider = delhivery_provider_for(self.session, tenant, option)
            new_forward = await _drift_neutral(provider, option, forward, booked, request.spec)
            if new_forward is None:
                return CarrierQuote.unavailable(option, QuoteUnavailableCode.PRICE_UNAVAILABLE, REPRICE_UNAVAILABLE_REASON)
            new_rto = await _drift_neutral(provider, option, rto, booked, request.spec) if rto is not None else None
        quote = CarrierQuote(
            option=option,
            serviceable=True,
            forward=new_forward,
            rto=new_rto,
            cod_supported=option != ServiceOption.DELHIVERY_B2B_SURFACE,
            snapshot=dict(record.get("snapshot") or {}),
        )
        return _with_rto_if_billed(quote, request.sell.include_rto)


REPRICE_UNAVAILABLE_REASON = (
    "Delhivery's price is unavailable right now, so this change can't be priced. The old price is kept; "
    "please try again in a few minutes."
)


@dataclass(frozen=True)
class RequoteRequest:
    """What a re-price needs: the option, the parcel after the change and the seller inputs."""

    option: ServiceOption
    spec: ParcelSpec
    sell: SellInputs


@dataclass(frozen=True)
class PriceResult:
    """
    A re-price result shaped like the old engine response (RepricingService reads these
    attribute names), plus the new server-only carrier record.
    """

    serviceable: bool
    error_message: Optional[str]
    total_amount: float
    base_charge: float
    tax_amount: float
    chargeable_weight: float
    pricing_breakdown: Dict[str, Any]
    carrier_cost: Optional[Dict[str, Any]]
    estimated_days: int = 0

    @classmethod
    def unserviceable(cls, reason: Optional[str]) -> "PriceResult":
        """A refusal (RepricingService turns it into H-7 ZeroQuoteError)."""
        return cls(False, reason, 0.0, 0.0, 0.0, 0.0, {}, None)

    @classmethod
    def of(
        cls,
        priced: PricedOption,
        spec: ParcelSpec,
        terms: SellTerms,
        previous: Optional[Mapping[str, Any]],
    ) -> "PriceResult":
        """Maps a priced option; keeps the ops `carrier_billed` block of the previous record."""
        billed = (previous or {}).get("carrier_billed")
        return cls(
            serviceable=True,
            error_message=None,
            total_amount=money_to_float(priced.sell.total),
            base_charge=money_to_float(priced.sell.forward_freight),
            tax_amount=money_to_float(priced.sell.gst),
            chargeable_weight=float(priced.chargeable_weight_kg),
            pricing_breakdown=priced.breakdown,
            carrier_cost=build_carrier_cost(priced.quote, spec, terms, billed),
            estimated_days=priced.transit_days or 0,
        )


def _with_rto_if_billed(quote: CarrierQuote, include_rto: bool) -> CarrierQuote:
    """Adds a provisional RTO leg when the RTO is billed but no RTO price exists."""
    if not include_rto or quote.rto is not None or quote.forward is None:
        return quote
    return replace(quote, rto=provisional_rto(quote.forward))


def _prime_lane_changed(record: Mapping[str, Any], request: "RequoteRequest") -> bool:
    """A Prime pin change means another lane: price it fresh instead of the frozen lane copy."""
    if request.option != ServiceOption.PRIME_SURFACE:
        return False
    booked = spec_from_json(record.get("inputs") or {})
    return (booked.pickup_pincode, booked.delivery_pincode) != (
        request.spec.pickup_pincode,
        request.spec.delivery_pincode,
    )


def _delhivery_inputs_changed(option: ServiceOption, booked: ParcelSpec, new: ParcelSpec) -> bool:
    """
    True when Delhivery would be asked a different question: B2C pins, leg or 500 g slab;
    B2B any estimate input (boxes, weight, pins, invoice value, risk type).
    """
    if not booked.packages:
        return True
    if option == ServiceOption.DELHIVERY_B2B_SURFACE:
        return estimate_body(booked) != estimate_body(new)
    ss = SS_REVERSE if new.shipment_type == ShipmentType.REVERSE else SS_FORWARD
    return price_params(option, booked, ss) != price_params(option, new, ss)


async def _drift_neutral(
    provider: "DelhiveryProvider | DelhiveryB2BProvider",
    option: ServiceOption,
    booked_leg: CarrierLeg,
    booked: ParcelSpec,
    new: ParcelSpec,
) -> Optional[CarrierLeg]:
    """
    `booked + (API(new) − API(booked inputs))` for one leg, both prices fresh and paired
    (Q8: pass through Delhivery's difference at booking-time rates). None when either call
    fails or the result is not positive (the caller refuses, H-7).
    """
    old_api = await provider.leg_for(option, booked, booked_leg.kind)
    new_api = await provider.leg_for(option, new, booked_leg.kind)
    if old_api is None or new_api is None:
        return None
    cost = to_money(booked_leg.cost + new_api.cost - old_api.cost)
    if cost <= ZERO_MONEY:
        return None
    details = dict(new_api.details)
    details["drift_neutral"] = {
        "booked": str(booked_leg.cost),
        "api_booked_inputs": str(old_api.cost),
        "api_new_inputs": str(new_api.cost),
    }
    return replace(new_api, cost=cost, lines=(), transit_days=booked_leg.transit_days, details=details)
