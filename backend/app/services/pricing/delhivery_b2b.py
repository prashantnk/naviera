"""
Delhivery B2B (Cargo / LTL) provider: carrier cost of the "Delhivery B2B Cargo (Surface)"
option for one LR (contract: llm_resources/.agents/pricing/delhivery_b2b_api.md).

- Request: `POST /freight/estimate` with the boxes (whole cm, identical sizes grouped),
  the total dead weight in grams, both pins, `payment_mode=prepaid` and `freight_mode=fop`
  (B2B COD and Freight-on-Delivery are off at launch), the declared invoice value and
  `rov_insurance` = carrier's risk.
- Freshness and fallback follow the B2C provider (DESIGN.md v4 Q6/Q7): "Get rates" reuses a
  stored answer ≤ 30 min; Book asks Delhivery first; when Delhivery is down a stored answer
  ≤ 24 h is used (flagged CACHED); otherwise "price unavailable" — never an invented price.
- Carrier cost = Delhivery's **pre-GST** estimate (Logismart adds its own 18 % GST).
- RTO leg = the estimate of the return lane (pins swapped), priced at booking.

Spring analogy: a second `@Component` strategy behind the same carrier-pricing interface
as `DelhiveryProvider`.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.money import ZERO_MONEY, money_to_float, to_money, to_weight
from app.models.pickups import ServiceOption
from app.models.tenants import Tenant
from app.repositories.delhivery_price_cache import DelhiveryPriceCacheRepository
from app.schemas.v1.pickups import PackageCreate
from app.services.pricing import weights
from app.services.pricing.delhivery import (
    FALLBACK_MAX_AGE,
    PT_PREPAID,
    SS_FORWARD,
    PriceFreshness,
    _Fetched,
    fetch_with_cache,
    slab_grams,
)
from app.services.pricing.delhivery_b2b_client import DelhiveryB2BApi, live_b2b_api_if_configured
from app.services.pricing.delhivery_client import (
    DelhiveryApi,
    DelhiveryRefusedError,
    DelhiveryUnavailableError,
    flag,
    is_embargoed,
    live_api_if_configured,
)
from app.services.pricing.fake_delhivery import FAKE_PROVIDER_TENANT_SLUGS
from app.services.pricing.fake_delhivery_b2b import FakeDelhiveryB2BApi
from app.services.pricing.types import (
    CarrierLeg,
    CarrierLegKind,
    CarrierQuote,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)

logger = logging.getLogger(__name__)

B2B_OPTION = ServiceOption.DELHIVERY_B2B_SURFACE
CACHE_KEY_PREFIX = "B2B"
CACHE_KEY_HASH_CHARS = 32
PAYMENT_MODE_PREPAID = "prepaid"
FREIGHT_MODE_ON_PICKUP = "fop"
"""`fop` = freight on pickup = Delhivery One's "Bill to Client" (Freight on Delivery is off)."""
GRAMS_PER_KG = Decimal("1000")
MIN_WEIGHT_GRAMS = 1
MIN_SIDE_CM = 1
PRE_TAX_KEYS = (
    "pre_tax_freight_charges",
    "pre_tax_amount",
    "pre_tax_total",
    "pre_tax_freight",
    "taxable_amount",
    "sub_total",
    "subtotal",
)
TOTAL_KEYS = ("total", "total_amount", "grand_total", "total_charges", "total_freight", "estimated_charges")
GST_KEYS = ("gst", "gst_amount", "tax", "tax_amount", "total_tax")
GST_PERCENT_KEYS = ("gst_percent", "gst_rate", "tax_percent")
CHARGED_KG_KEYS = ("chargeable_weight_kg", "charged_weight_kg")
BREAKUP_KEYS = ("price_breakup", "breakup", "charges", "freight_breakup")
HUNDRED = Decimal("100")

NOT_CONNECTED_REASON = (
    "Delhivery B2B Cargo prices are not connected yet. Please use Logismart Prime or contact Logismart."
)
UNAVAILABLE_REASON = "Delhivery B2B Cargo's price is unavailable right now. Please try again in a few minutes."
NO_BOXES_REASON = "Add the boxes with their size and weight to get a Delhivery B2B Cargo price."
REFUSED_REASON = "Delhivery B2B Cargo can't serve this route: {detail}"
PIN_NOT_SERVED = "Delhivery B2B Cargo does not serve PIN {pin}."


B2C_SURFACE_MODE = "S"
FALLBACK_ROV_RATE = Decimal("0.001")
FALLBACK_MIN_ROV = Decimal("100.00")
FALLBACK_GST_RATE = Decimal("0.18")


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fallback_chargeable_grams(body: Mapping[str, Any]) -> int:
    """
    Total chargeable weight in grams across all boxes (max of dead weight and L×W×H / 5000),
    rounded up to Delhivery's 500 g slab.
    """
    dead_grams = int(body.get("weight_g") or 0)
    dims = body.get("dimensions") or ()
    vol_cm3 = sum(
        (
            Decimal(int(item.get("length_cm") or 0))
            * Decimal(int(item.get("width_cm") or 0))
            * Decimal(int(item.get("height_cm") or 0))
            * Decimal(int(item.get("box_count") or 0))
            for item in dims
            if isinstance(item, Mapping)
        ),
        Decimal("0"),
    )
    vol_grams = int(
        (vol_cm3 * GRAMS_PER_KG / weights.DELHIVERY_VOLUMETRIC_DIVISOR).to_integral_value(rounding=ROUND_CEILING)
    )
    return slab_grams(max(dead_grams, vol_grams, MIN_WEIGHT_GRAMS))


def _fallback_rov_charge(body: Mapping[str, Any]) -> Decimal:
    """Carrier's risk ROV charge (`max(0.1% * inv_amount, ₹100)`) when `rov_insurance=True`, else ₹0."""
    if not body.get("rov_insurance"):
        return ZERO_MONEY
    invoice = Decimal(str(body.get("inv_amount") or 0))
    return to_money(max(invoice * FALLBACK_ROV_RATE, FALLBACK_MIN_ROV))


class B2CFallbackDelhiveryB2BApi:
    """
    B2B estimator adapter backed by Delhivery's B2C Surface API (`kinko/v1/invoice/charges/.json`,
    `md=S`) when `DELHIVERY_B2B_PASSWORD` is not yet configured in `.env` but `DELHIVERY_B2C_TOKEN`
    is present. Automatically yields to `LiveDelhiveryB2BApi` once `DELHIVERY_B2B_PASSWORD` is set.
    """

    def __init__(self, b2c_api: DelhiveryApi) -> None:
        self._b2c = b2c_api

    async def estimate(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """Prices the B2B box payload via `kinko/v1/invoice/charges/.json` (`md=S`) + optional ROV."""
        cgm = _fallback_chargeable_grams(body)
        params = {
            "md": B2C_SURFACE_MODE,
            "ss": SS_FORWARD,
            "o_pin": str(body["source_pin"]),
            "d_pin": str(body["consignee_pin"]),
            "cgm": cgm,
            "pt": PT_PREPAID,
        }
        raw = await self._b2c.invoice_charges(params)
        gross = max(to_money(raw.get("gross_amount")) - to_money(raw.get("charge_COD")), ZERO_MONEY)
        if gross <= ZERO_MONEY:
            raise DelhiveryUnavailableError("Delhivery B2C fallback returned zero gross_amount.")
        rov = _fallback_rov_charge(body)
        pre_tax = to_money(gross + rov)
        gst = to_money(pre_tax * FALLBACK_GST_RATE)
        total = to_money(pre_tax + gst)
        charged_grams = Decimal(str(raw.get("charged_weight") or cgm))
        charged_kg = float(to_weight(charged_grams / GRAMS_PER_KG))
        return {
            "success": True,
            "fallback_source": "DELHIVERY_B2C_SURFACE",
            "data": {
                "pre_tax_freight_charges": money_to_float(pre_tax),
                "gst": money_to_float(gst),
                "total": money_to_float(total),
                "chargeable_weight_kg": charged_kg,
                "zone": raw.get("zone"),
                "price_breakup": {
                    "base_freight": money_to_float(gross),
                    "rov_charges": money_to_float(rov),
                    "gst": money_to_float(gst),
                },
            },
        }

    async def pincode_serviceable(self, pincode: str, weight_g: int) -> bool:
        """Checks pincode serviceability via the B2C pincode API (non-embargoed, prepaid/pickup active)."""
        record = await self._b2c.pincode(pincode)
        if record is None or is_embargoed(record):
            return False
        return bool(flag(record, "pre_paid") or flag(record, "pickup"))

    async def tat_days(self, origin_pin: str, destination_pin: str) -> Optional[int]:
        """Surface (`mot=S`) expected transit days from the B2C TAT API."""
        return await self._b2c.expected_tat(origin_pin, destination_pin, B2C_SURFACE_MODE)


def delhivery_b2b_api_for(tenant: Tenant) -> Optional[DelhiveryB2BApi]:
    """
    The fake for the golden test tenant, the live B2B LTL client when B2B credentials
    are configured, else the B2C Surface fallback when the B2C token is configured.
    """
    if tenant.slug in FAKE_PROVIDER_TENANT_SLUGS:
        return FakeDelhiveryB2BApi(tenant.slug)
    tid = str(tenant.id)
    b2b_api = live_b2b_api_if_configured(tid)
    if b2b_api is not None:
        return b2b_api
    b2c_api = live_api_if_configured(tid)
    if b2c_api is not None:
        return B2CFallbackDelhiveryB2BApi(b2c_api)
    return None


# --- request ---------------------------------------------------------------------------


def _whole_cm(value: Decimal) -> int:
    """A side in whole centimetres, rounded up (Delhivery takes integers), at least 1 cm."""
    return max(MIN_SIDE_CM, int(value.to_integral_value(rounding=ROUND_CEILING)))


def dimensions_payload(packages: Iterable[PackageCreate]) -> List[Dict[str, int]]:
    """
    The `dimensions` list: one entry per distinct box size (cm, rounded up), counts summed.

    Args:
        packages: The declared boxes (any unit).

    Returns:
        Sorted list of `{length_cm, width_cm, height_cm, box_count}` (stable for cache keys).
    """
    counts: Dict[Tuple[int, int, int], int] = {}
    for package in packages:
        size = tuple(_whole_cm(side) for side in weights.box_dimensions_cm(package))
        counts[size] = counts.get(size, 0) + int(package.box_count)  # type: ignore[index]
    return [
        {"length_cm": length, "width_cm": width, "height_cm": height, "box_count": count}
        for (length, width, height), count in sorted(counts.items())
    ]


def weight_grams(packages: Iterable[PackageCreate]) -> int:
    """Total dead weight of the LR in whole grams (rounded up, at least 1 g)."""
    grams = (weights.total_actual_kg(packages) * GRAMS_PER_KG).to_integral_value(rounding=ROUND_CEILING)
    return max(MIN_WEIGHT_GRAMS, int(grams))


def estimate_body(spec: ParcelSpec, kind: CarrierLegKind = CarrierLegKind.FORWARD) -> Dict[str, Any]:
    """
    The exact `POST /freight/estimate` body for a leg (RTO = the return lane, pins swapped).

    Args:
        spec: The LR.
        kind: FORWARD or RTO.

    Returns:
        JSON-safe request body.
    """
    origin, destination = spec.pickup_pincode, spec.delivery_pincode
    if kind == CarrierLegKind.RTO:
        origin, destination = destination, origin
    return {
        "dimensions": dimensions_payload(spec.packages),
        "weight_g": weight_grams(spec.packages),
        "source_pin": origin,
        "consignee_pin": destination,
        "payment_mode": PAYMENT_MODE_PREPAID,
        "freight_mode": FREIGHT_MODE_ON_PICKUP,
        "inv_amount": money_to_float(to_money(spec.invoice_value)),
        "rov_insurance": bool(spec.carriers_risk),
        "cheque_payment": False,
    }


def cache_key(body: Mapping[str, Any]) -> str:
    """`B2B|source|consignee|<sha256 of the canonical body>` (fits VARCHAR(200))."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:CACHE_KEY_HASH_CHARS]
    return f"{CACHE_KEY_PREFIX}|{body['source_pin']}|{body['consignee_pin']}|{digest}"


# --- response ----------------------------------------------------------------------------


@dataclass(frozen=True)
class EstimateAmounts:
    """The money read from one estimate answer (pre-GST cost is what Logismart pays)."""

    pre_tax: Decimal
    gst: Optional[Decimal]
    total: Optional[Decimal]
    charged_weight_kg: Optional[Decimal]
    breakup: Dict[str, float]


def _containers(response: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The dicts that may hold amounts: `data` (or the body) and its breakup block."""
    data: Any = response.get("data", response)
    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict)), None)
    if not isinstance(data, dict):
        return []
    found: List[Mapping[str, Any]] = [data]
    found.extend(data[key] for key in BREAKUP_KEYS if isinstance(data.get(key), dict))
    return found


def _first_amount(containers: List[Mapping[str, Any]], keys: Tuple[str, ...]) -> Optional[Decimal]:
    """The first numeric value under any of `keys` (containers in order), as Decimal."""
    for container in containers:
        for key in keys:
            value = container.get(key)
            if value is None or isinstance(value, (bool, dict, list)):
                continue
            try:
                return Decimal(str(value))
            except InvalidOperation:
                continue
    return None


def _numeric_breakup(containers: List[Mapping[str, Any]]) -> Dict[str, float]:
    """Numeric lines of the breakup block (server-only audit detail)."""
    breakup = containers[1] if len(containers) > 1 else {}
    return {
        key: float(value)
        for key, value in breakup.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _pre_tax(containers: List[Mapping[str, Any]], total: Optional[Decimal], gst: Optional[Decimal]) -> Optional[Decimal]:
    """Explicit pre-GST amount, else total − GST, else total ÷ (1 + GST %)."""
    explicit = _first_amount(containers, PRE_TAX_KEYS)
    if explicit is not None:
        return explicit
    if total is not None and gst is not None:
        return total - gst
    percent = _first_amount(containers, GST_PERCENT_KEYS)
    if total is not None and percent is not None:
        return total * HUNDRED / (HUNDRED + percent)
    return None


def estimate_amounts(response: Mapping[str, Any]) -> Optional[EstimateAmounts]:
    """
    Reads the pre-GST cost (and GST / total / charged weight when present) of an estimate.

    The response body is not publicly documented, so the reader accepts the plausible key
    names and refuses (None) instead of guessing when no pre-GST amount can be derived.

    Args:
        response: Raw `POST /freight/estimate` JSON object.

    Returns:
        The amounts, or None when no positive pre-GST amount is present.
    """
    containers = _containers(response)
    total = _first_amount(containers, TOTAL_KEYS)
    gst = _first_amount(containers, GST_KEYS)
    pre_tax = _pre_tax(containers, total, gst)
    if pre_tax is None or to_money(pre_tax) <= ZERO_MONEY:
        return None
    return EstimateAmounts(
        pre_tax=to_money(pre_tax),
        gst=to_money(gst) if gst is not None else None,
        total=to_money(total) if total is not None else None,
        charged_weight_kg=_first_amount(containers, CHARGED_KG_KEYS),
        breakup=_numeric_breakup(containers),
    )


def _fallback_charged_kg(spec: ParcelSpec) -> Decimal:
    """Displayed chargeable weight when Delhivery doesn't echo one: max(dead, L×B×H / 5000)."""
    return to_weight(Decimal(weights.delhivery_chargeable_grams(spec.packages)) / GRAMS_PER_KG)


def leg_from_estimate(
    kind: CarrierLegKind, fetched: _Fetched, transit_days: Optional[int], spec: ParcelSpec
) -> Optional[CarrierLeg]:
    """
    Maps an estimate answer to a carrier leg (cost = pre-GST estimate), or None when unreadable.

    Details are JSON-safe and server-only (never on a customer response).
    """
    amounts = estimate_amounts(fetched.response)
    if amounts is None:
        logger.error("Delhivery B2B estimate had no readable pre-GST amount (keys: %s)", sorted(fetched.response))
        return None
    charged = amounts.charged_weight_kg if amounts.charged_weight_kg is not None else _fallback_charged_kg(spec)
    return CarrierLeg(
        kind=kind,
        cost=amounts.pre_tax,
        lines=(),
        charged_weight_kg=to_weight(charged),
        transit_days=transit_days,
        source=fetched.source,
        fetched_at=fetched.fetched_at,
        details={
            "carrier": "DELHIVERY_B2B",
            "pre_tax": money_to_float(amounts.pre_tax),
            "gst": money_to_float(amounts.gst) if amounts.gst is not None else None,
            "gross": money_to_float(amounts.total) if amounts.total is not None else None,
            "charges": amounts.breakup,
            "fetched_at": fetched.fetched_at.isoformat(),
        },
    )


# --- provider -------------------------------------------------------------------------------


class DelhiveryB2BProvider:
    """Delhivery B2B Cargo carrier cost for one tenant (cache + live / fake client)."""

    def __init__(
        self,
        session: AsyncSession,
        tenant: Tenant,
        *,
        api: Optional[DelhiveryB2BApi] = None,
    ) -> None:
        self.tenant = tenant
        self.cache = DelhiveryPriceCacheRepository(session)
        self.api = api if api is not None else delhivery_b2b_api_for(tenant)

    @property
    def configured(self) -> bool:
        """False → the option is 'not connected yet'."""
        return self.api is not None

    async def quote(
        self,
        option: ServiceOption,
        spec: ParcelSpec,
        *,
        freshness: PriceFreshness,
        include_rto: bool,
        is_cod: bool = False,
    ) -> CarrierQuote:
        """
        The carrier answer for the Delhivery B2B option (same signature as the B2C provider).

        Args:
            option: DELHIVERY_B2B_SURFACE.
            spec: The LR.
            freshness: QUOTE (rate cards) or BOOK (ask Delhivery first).
            include_rto: Also price the return lane (booking).
            is_cod: Unused (COD is refused before the provider for B2B).

        Returns:
            A serviceable quote, or an unavailable one with a plain-English reason.
        """
        if self.api is None:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.PRICE_UNAVAILABLE, NOT_CONNECTED_REASON)
        if not spec.packages:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.NOT_SERVICEABLE, NO_BOXES_REASON)
        refusal = await self._serviceability_refusal(option, spec)
        if refusal is not None:
            return refusal
        body = estimate_body(spec)
        try:
            fetched = await self._estimate(body, freshness)
        except DelhiveryRefusedError as exc:
            return CarrierQuote.unavailable(
                option, QuoteUnavailableCode.NOT_SERVICEABLE, REFUSED_REASON.format(detail=exc)
            )
        forward = (
            leg_from_estimate(CarrierLegKind.FORWARD, fetched, await self._transit_days(spec), spec)
            if fetched is not None
            else None
        )
        if forward is None:
            return CarrierQuote.unavailable(option, QuoteUnavailableCode.PRICE_UNAVAILABLE, UNAVAILABLE_REASON)
        rto = await self._rto_leg(spec) if include_rto else None
        return CarrierQuote(
            option=option,
            serviceable=True,
            forward=forward,
            rto=rto,
            cod_supported=False,
            snapshot={"request": body},
        )

    async def leg_for(self, option: ServiceOption, spec: ParcelSpec, kind: CarrierLegKind) -> Optional[CarrierLeg]:
        """
        One fresh leg for drift-neutral re-pricing: asks Delhivery, falls back to a stored
        answer ≤ 24 h, else None (refusals too; the caller refuses the change, H-7).
        """
        if self.api is None or not spec.packages:
            return None
        try:
            fetched = await self._estimate(estimate_body(spec, kind), PriceFreshness.BOOK)
        except DelhiveryRefusedError:
            return None
        return leg_from_estimate(kind, fetched, None, spec) if fetched is not None else None

    async def _estimate(self, body: Dict[str, Any], freshness: PriceFreshness) -> Optional[_Fetched]:
        """Shared cache rules (≤ 30 min quote reuse, ≤ 24 h fallback) around one estimate call."""
        return await fetch_with_cache(
            self.cache,
            self.tenant.id,
            cache_key(body),
            body,
            freshness,
            lambda: self.api.estimate(body),  # type: ignore[union-attr]
        )

    async def _rto_leg(self, spec: ParcelSpec) -> Optional[CarrierLeg]:
        """Return-lane leg at booking: stored ≤ 24 h, else one call; None when Delhivery can't answer."""
        body = estimate_body(spec, CarrierLegKind.RTO)
        cached = await self.cache.get(self.tenant.id, cache_key(body))
        if cached is not None and _utc_now_naive() - cached.fetched_at <= FALLBACK_MAX_AGE:
            stored = _Fetched(dict(cached.response), cached.fetched_at, PriceSource.CACHED)
            return leg_from_estimate(CarrierLegKind.RTO, stored, None, spec)
        return await self.leg_for(B2B_OPTION, spec, CarrierLegKind.RTO)

    async def _transit_days(self, spec: ParcelSpec) -> Optional[int]:
        """Delhivery B2B TAT (24 h in-process cache); None when unknown or down."""
        try:
            return await self.api.tat_days(spec.pickup_pincode, spec.delivery_pincode)  # type: ignore[union-attr]
        except (DelhiveryUnavailableError, DelhiveryRefusedError):
            return None

    async def _serviceability_refusal(self, option: ServiceOption, spec: ParcelSpec) -> Optional[CarrierQuote]:
        """An unavailable quote when Delhivery B2B does not serve a pin; lookup failures never block."""
        grams = weight_grams(spec.packages)
        for pin in (spec.pickup_pincode, spec.delivery_pincode):
            try:
                served = await self.api.pincode_serviceable(pin, grams)  # type: ignore[union-attr]
            except (DelhiveryUnavailableError, DelhiveryRefusedError):
                return None  # the estimate decides
            if not served:
                return CarrierQuote.unavailable(
                    option, QuoteUnavailableCode.NOT_SERVICEABLE, PIN_NOT_SERVED.format(pin=pin)
                )
        return None
