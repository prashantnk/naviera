"""
Delhivery B2C provider: carrier cost of Delhivery Surface / Express for one parcel
(DESIGN.md v4 §A "Price timing", §C.3; delhivery_api.md §2.1, §3).

- Price request: `md` (S/E), `ss` (Delivered / DTO for reverse / RTO), `o_pin`, `d_pin`,
  `cgm` (chargeable grams rounded up to the 500 g slab, so a cached answer matches the
  request exactly), `pt=Pre-paid` (Logismart charges its own COD fee, Q9).
- Freshness: "Get rates" reuses a stored answer ≤ 30 min old; Book always asks Delhivery
  first (Q7). When Delhivery is down / throttled either path falls back to a stored answer
  ≤ 24 h old (Q6), flagged CACHED; otherwise the option is "price unavailable" — a price is
  never invented and never ₹0 (H-7).
- The RTO leg is priced at booking (stored answer ≤ 24 h, else one call; skipped when
  Delhivery is down — re-pricing then bills a provisional RTO).

Spring analogy: a `@Component` strategy implementing a `CarrierPricingProvider` interface.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.money import ZERO_MONEY, money_to_float, to_money, to_weight
from app.models.pickups import ServiceOption, ShipmentType
from app.models.tenants import Tenant
from app.repositories.delhivery_price_cache import DelhiveryPriceCacheRepository
from app.services.pricing import weights
from app.services.pricing.delhivery_client import (
    DelhiveryApi,
    DelhiveryRefusedError,
    DelhiveryUnavailableError,
    flag,
    is_embargoed,
    live_api_if_configured,
)
from app.services.pricing.fake_delhivery import FAKE_PROVIDER_TENANT_SLUGS, FakeDelhiveryApi
from app.services.pricing.types import (
    CarrierLeg,
    CarrierLegKind,
    CarrierQuote,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)

logger = logging.getLogger(__name__)

OPTION_MODE: Dict[ServiceOption, str] = {
    ServiceOption.DELHIVERY_SURFACE: "S",
    ServiceOption.DELHIVERY_EXPRESS: "E",
}
"""Delhivery `md` per option (E = Express, Air where Delhivery can)."""
SS_FORWARD = "Delivered"
SS_RTO = "RTO"
SS_REVERSE = "DTO"
PT_PREPAID = "Pre-paid"
SLAB_GRAMS = 500
GRAMS_PER_KG = Decimal("1000")
FRESH_MAX_AGE = timedelta(minutes=30)
FALLBACK_MAX_AGE = timedelta(hours=24)
NOT_CONNECTED_REASON = "Delhivery prices are not connected yet. Please try again later or contact Logismart."
UNAVAILABLE_REASON = "Delhivery's price is unavailable right now. Please try again in a few minutes."
NO_BOXES_REASON = "Add at least one box with its size and weight to get a Delhivery price."
REFUSED_REASON = "Delhivery can't serve this route: {detail}"
ORIGIN_NOT_SERVED = "Delhivery does not pick up from PIN {pin}."
DESTINATION_NOT_SERVED = "Delhivery does not deliver to PIN {pin}."
EMBARGO_REASON = "Delhivery has paused service at PIN {pin} for now (embargo). Please try later."
COD_NOT_SERVED = "Cash on Delivery isn't available at PIN {pin}. Choose Prepaid for this order."


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PriceFreshness(str, Enum):
    """How hard to insist on a live price."""

    QUOTE = "QUOTE"
    """Rate cards: a stored answer ≤ 30 min is fine."""
    BOOK = "BOOK"
    """Book / re-price: ask Delhivery first; stored ≤ 24 h only when it is down."""


@dataclass(frozen=True)
class _Fetched:
    """A price answer and where it came from."""

    response: Dict[str, Any]
    fetched_at: datetime
    source: PriceSource


def delhivery_api_for(tenant: Tenant) -> Optional[DelhiveryApi]:
    """
    The Delhivery client for a tenant: the fake for the golden test tenant, the live
    client for the tenant bound to the token, otherwise None ("not connected").
    """
    if tenant.slug in FAKE_PROVIDER_TENANT_SLUGS:
        return FakeDelhiveryApi(tenant.slug)
    return live_api_if_configured(str(tenant.id))


def slab_grams(grams: int) -> int:
    """Chargeable grams rounded up to Delhivery's 500 g slab (never below one slab)."""
    return max(SLAB_GRAMS, -(-int(grams) // SLAB_GRAMS) * SLAB_GRAMS)


def price_params(option: ServiceOption, spec: ParcelSpec, ss: str) -> Dict[str, Any]:
    """The exact Delhivery price query for an option, parcel and leg."""
    return {
        "md": OPTION_MODE[option],
        "ss": ss,
        "o_pin": spec.pickup_pincode,
        "d_pin": spec.delivery_pincode,
        "cgm": slab_grams(weights.delhivery_chargeable_grams(spec.packages)),
        "pt": PT_PREPAID,
    }


def cache_key(params: Dict[str, Any]) -> str:
    """Stable cache key of a price query (o_pin|d_pin|md|ss|pt|cgm)."""
    return "|".join(str(params[name]) for name in ("o_pin", "d_pin", "md", "ss", "pt", "cgm"))


async def fetch_with_cache(
    cache: DelhiveryPriceCacheRepository,
    tenant_id: uuid.UUID,
    key: str,
    request_params: Dict[str, Any],
    freshness: PriceFreshness,
    call: Callable[[], Awaitable[Dict[str, Any]]],
) -> Optional[_Fetched]:
    """
    One Delhivery price answer with the shared cache rules (B2C price API and B2B estimate).

    Stored ≤ 30 min (QUOTE only) → live call (stored on success) → stored ≤ 24 h flagged
    CACHED when Delhivery is unavailable → None. Business refusals propagate to the caller.

    Args:
        cache: The tenant-scoped price cache repository.
        tenant_id: The tenant whose Delhivery account answers.
        key: Exact cache key of the request.
        request_params: The request as stored next to the answer.
        freshness: QUOTE or BOOK.
        call: Performs the live request (raises Delhivery*Error).

    Returns:
        The answer and its source, or None when nothing usable exists.
    """
    cached = await cache.get(tenant_id, key)
    now = _utc_now_naive()
    if freshness == PriceFreshness.QUOTE and cached is not None and now - cached.fetched_at <= FRESH_MAX_AGE:
        return _Fetched(dict(cached.response), cached.fetched_at, PriceSource.LIVE)
    try:
        response = await call()
    except DelhiveryUnavailableError as exc:
        logger.warning("Delhivery price unavailable (%s); trying the stored price.", exc)
        if cached is not None and now - cached.fetched_at <= FALLBACK_MAX_AGE:
            return _Fetched(dict(cached.response), cached.fetched_at, PriceSource.CACHED)
        return None
    await cache.upsert(tenant_id=tenant_id, cache_key=key, request_params=request_params, response=response, fetched_at=now)
    return _Fetched(response, now, PriceSource.LIVE)


def leg_from_response(kind: CarrierLegKind, fetched: _Fetched, transit_days: Optional[int]) -> CarrierLeg:
    """
    Maps `resp[0]` to a carrier leg. Freight = gross − charge_COD (pre-GST; Logismart adds
    its own GST and COD fee). Details are JSON-safe and server-only.
    """
    response = fetched.response
    gross = to_money(response.get("gross_amount"))
    charge_cod = to_money(response.get("charge_COD"))
    cost = max(to_money(gross - charge_cod), ZERO_MONEY)
    charged_grams = Decimal(str(response.get("charged_weight") or 0))
    charges = {
        key: float(value)
        for key, value in response.items()
        if key.startswith("charge_") and isinstance(value, (int, float)) and value
    }
    return CarrierLeg(
        kind=kind,
        cost=cost,
        lines=(),
        charged_weight_kg=to_weight(charged_grams / GRAMS_PER_KG),
        transit_days=transit_days,
        source=fetched.source,
        fetched_at=fetched.fetched_at,
        details={
            "zone": response.get("zone"),
            "gross": money_to_float(gross),
            "charge_COD": money_to_float(charge_cod),
            "charges": charges,
            "charged_weight_g": float(charged_grams),
            "fetched_at": fetched.fetched_at.isoformat(),
        },
    )


def return_only_leg(cumulative: CarrierLeg, forward: CarrierLeg) -> Optional[CarrierLeg]:
    """
    The return-only RTO leg. Delhivery's `ss=RTO` price is cumulative (forward + return:
    prod check 2026-11-01, 110037→400001 500 g: RTO gross ₹69.39 = Delivered ₹35.69 + return
    ₹33.70), and the forward leg is billed separately, so RTO cost = RTO gross − forward cost.

    Returns:
        The leg, or None when the difference is not positive (re-pricing then bills a
        provisional RTO, flagged for ops).
    """
    cost = to_money(cumulative.cost - forward.cost)
    if cost <= ZERO_MONEY:
        return None
    details = dict(cumulative.details)
    details.update({"cumulative_cost": str(cumulative.cost), "forward_cost": str(forward.cost)})
    return CarrierLeg(
        kind=CarrierLegKind.RTO,
        cost=cost,
        lines=(),
        charged_weight_kg=cumulative.charged_weight_kg,
        transit_days=None,
        source=cumulative.source,
        fetched_at=cumulative.fetched_at,
        details=details,
    )


class DelhiveryProvider:
    """Delhivery carrier cost for one tenant (cache + live / fake client)."""

    def __init__(
        self,
        session: AsyncSession,
        tenant: Tenant,
        *,
        api: Optional[DelhiveryApi] = None,
    ) -> None:
        self.tenant = tenant
        self.cache = DelhiveryPriceCacheRepository(session)
        self.api = api if api is not None else delhivery_api_for(tenant)

    @property
    def configured(self) -> bool:
        """False → every Delhivery option is 'not connected yet'."""
        return self.api is not None

    async def quote(
        self,
        option: ServiceOption,
        spec: ParcelSpec,
        *,
        freshness: PriceFreshness,
        include_rto: bool,
        is_cod: bool,
    ) -> CarrierQuote:
        """
        The carrier answer for one Delhivery option.

        Args:
            option: DELHIVERY_SURFACE or DELHIVERY_EXPRESS.
            spec: The parcel.
            freshness: QUOTE (rate cards) or BOOK (always ask Delhivery first).
            include_rto: Also price the RTO leg (booking).
            is_cod: The seller asked for COD (pincode COD check).

        Returns:
            A serviceable quote, or an unavailable one with a plain-English reason.
        """
        if self.api is None:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.PRICE_UNAVAILABLE, NOT_CONNECTED_REASON)
        if not spec.packages:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.NOT_SERVICEABLE, NO_BOXES_REASON)
        refusal = await self._serviceability_refusal(option, spec, is_cod)
        if refusal is not None:
            return refusal
        is_reverse = spec.shipment_type == ShipmentType.REVERSE
        params = price_params(option, spec, SS_REVERSE if is_reverse else SS_FORWARD)
        try:
            fetched = await self._price(params, freshness)
        except DelhiveryRefusedError as exc:
            return CarrierQuote.unavailable(
                option, QuoteUnavailableCode.NOT_SERVICEABLE, REFUSED_REASON.format(detail=exc)
            )
        if fetched is None:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.PRICE_UNAVAILABLE, UNAVAILABLE_REASON)
        transit = await self._transit_days(spec, OPTION_MODE[option])
        kind = CarrierLegKind.REVERSE if is_reverse else CarrierLegKind.FORWARD
        forward = leg_from_response(kind, fetched, transit)
        if forward.cost <= ZERO_MONEY:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.PRICE_UNAVAILABLE, UNAVAILABLE_REASON)
        rto = await self._rto_leg(option, spec, forward) if include_rto and not is_reverse else None
        return CarrierQuote(
            option=option,
            serviceable=True,
            forward=forward,
            rto=rto,
            cod_supported=True,
            snapshot={"request": params},
        )

    async def leg_for(
        self, option: ServiceOption, spec: ParcelSpec, kind: CarrierLegKind
    ) -> Optional[CarrierLeg]:
        """
        One fresh leg for re-pricing (drift-neutral pairs): asks Delhivery, falls back to a
        stored answer ≤ 24 h, else None. Refusals return None too (the caller refuses H-7).
        """
        if self.api is None or not spec.packages:
            return None
        if kind == CarrierLegKind.RTO:
            forward = await self.leg_for(option, spec, CarrierLegKind.FORWARD)
            cumulative = await self._fresh_leg(option, spec, CarrierLegKind.RTO)
            return return_only_leg(cumulative, forward) if cumulative and forward else None
        return await self._fresh_leg(option, spec, kind)

    async def _fresh_leg(self, option: ServiceOption, spec: ParcelSpec, kind: CarrierLegKind) -> Optional[CarrierLeg]:
        """One leg as Delhivery quotes it (`ss=RTO` is cumulative); None on refusal / outage."""
        ss = {CarrierLegKind.FORWARD: SS_FORWARD, CarrierLegKind.REVERSE: SS_REVERSE}.get(kind, SS_RTO)
        try:
            fetched = await self._price(price_params(option, spec, ss), PriceFreshness.BOOK)
        except DelhiveryRefusedError:
            return None
        return leg_from_response(kind, fetched, None) if fetched is not None else None

    async def _price(self, params: Dict[str, Any], freshness: PriceFreshness) -> Optional[_Fetched]:
        """Stored ≤ 30 min (QUOTE only) → live call (stored) → stored ≤ 24 h → None."""
        return await fetch_with_cache(
            self.cache,
            self.tenant.id,
            cache_key(params),
            params,
            freshness,
            lambda: self.api.invoice_charges(params),  # type: ignore[union-attr]
        )

    async def _rto_leg(self, option: ServiceOption, spec: ParcelSpec, forward: CarrierLeg) -> Optional[CarrierLeg]:
        """
        Return-only RTO leg at booking: Delhivery's `ss=RTO` answer (stored ≤ 24 h, else one
        call) minus the forward leg; None when Delhivery can't answer.
        """
        params = price_params(option, spec, SS_RTO)
        cached = await self.cache.get(self.tenant.id, cache_key(params))
        if cached is not None and _utc_now_naive() - cached.fetched_at <= FALLBACK_MAX_AGE:
            stored = _Fetched(dict(cached.response), cached.fetched_at, PriceSource.CACHED)
            return return_only_leg(leg_from_response(CarrierLegKind.RTO, stored, None), forward)
        cumulative = await self._fresh_leg(option, spec, CarrierLegKind.RTO)
        return return_only_leg(cumulative, forward) if cumulative is not None else None

    async def _transit_days(self, spec: ParcelSpec, mot: str) -> Optional[int]:
        """Delhivery TAT (24 h in-process cache); None when unknown or down."""
        try:
            return await self.api.expected_tat(spec.pickup_pincode, spec.delivery_pincode, mot)  # type: ignore[union-attr]
        except (DelhiveryUnavailableError, DelhiveryRefusedError):
            return None

    async def _serviceability_refusal(
        self, option: ServiceOption, spec: ParcelSpec, is_cod: bool
    ) -> Optional[CarrierQuote]:
        """An unavailable quote when Delhivery's pincode data refuses the route; None otherwise."""
        try:
            origin = await self.api.pincode(spec.pickup_pincode)  # type: ignore[union-attr]
            destination = await self.api.pincode(spec.delivery_pincode)  # type: ignore[union-attr]
        except DelhiveryUnavailableError:
            return None  # the price call decides; never block on the lookup alone
        not_served = QuoteUnavailableCode.NOT_SERVICEABLE
        if origin is None:
            return CarrierQuote.unavailable(option, not_served, ORIGIN_NOT_SERVED.format(pin=spec.pickup_pincode))
        if destination is None:
            return CarrierQuote.unavailable(
                option, not_served, DESTINATION_NOT_SERVED.format(pin=spec.delivery_pincode)
            )
        for pin, record in ((spec.pickup_pincode, origin), (spec.delivery_pincode, destination)):
            if is_embargoed(record):
                return CarrierQuote.unavailable(option, QuoteUnavailableCode.EMBARGO, EMBARGO_REASON.format(pin=pin))
        pickup_flag = "repl" if spec.shipment_type == ShipmentType.REVERSE else "pickup"
        if not flag(origin, pickup_flag) and not flag(origin, "pickup"):
            return CarrierQuote.unavailable(option, not_served, ORIGIN_NOT_SERVED.format(pin=spec.pickup_pincode))
        if is_cod and not flag(destination, "cod"):
            return CarrierQuote.unavailable(
                option, QuoteUnavailableCode.COD_NOT_AVAILABLE, COD_NOT_SERVED.format(pin=spec.delivery_pincode)
            )
        if not is_cod and not flag(destination, "pre_paid"):
            return CarrierQuote.unavailable(
                option, not_served, DESTINATION_NOT_SERVED.format(pin=spec.delivery_pincode)
            )
        return None
