"""
Shared value types of the pricing package (DESIGN.md v4 §C.2/C.3).

A *service option* (carrier × mode × rate source) is priced in two layers:

1. **Carrier cost** (`CarrierQuote` / `CarrierLeg`): what Delhivery or the Prime
   transporter charges Logismart, pre-GST. Produced by a provider (Delhivery
   client or Prime rate table). Server-only: it lands in
   `payment_details.carrier_cost` and is never serialised to a customer.
2. **Sell price** (`sell_price.py`): carrier cost × (1 + markup) + Logismart's COD
   fee + 18 % GST. This is what the seller is billed.

Spring analogy: plain immutable DTOs (Java records) shared by the
`@Component` pricing strategies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from app.models.pickups import ServiceOption, ShipmentType
from app.schemas.v1.pickups import PackageCreate


class PriceSource(str, Enum):
    """Where a carrier leg price came from."""

    LIVE = "LIVE"
    """A fresh provider answer (Delhivery API call or the fake provider)."""
    CACHED = "CACHED"
    """A stored Delhivery answer from `delhivery_price_cache`."""
    TABLE = "TABLE"
    """Computed from a Prime lane (rate table), live or frozen at booking."""
    PROVISIONAL = "PROVISIONAL"
    """RTO leg billed at the forward cost because no RTO price was stored (flagged for ops)."""


class CarrierLegKind(str, Enum):
    """Which journey a leg prices."""

    FORWARD = "FORWARD"
    RTO = "RTO"
    REVERSE = "REVERSE"


class QuoteUnavailableCode(str, Enum):
    """Why an option card is greyed out (plain-English reason travels next to it)."""

    NOT_SERVICEABLE = "NOT_SERVICEABLE"
    EMBARGO = "EMBARGO"
    NO_PRIME_LANE = "NO_PRIME_LANE"
    PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
    OPTION_DISABLED = "OPTION_DISABLED"
    TOO_LARGE = "TOO_LARGE"
    COD_NOT_AVAILABLE = "COD_NOT_AVAILABLE"


@dataclass(frozen=True)
class ParcelSpec:
    """
    Everything a carrier needs to price one shipment option.

    Attributes:
        pickup_pincode: 6-digit origin pincode.
        delivery_pincode: 6-digit destination pincode.
        packages: Declared (or measured) boxes; empty only for a blind pickup.
        shipment_type: FORWARD or REVERSE (reverse = DTO for Delhivery).
        is_blind_pickup: B2B dock pickup without box details (priced on the minimum weight).
        estimated_box_count: Carton estimate for a blind pickup.
        door_delivery: Prime add-on: deliver to the door instead of the transporter godown.
        invoice_value: Declared goods total (value + tax); Delhivery B2B prices its risk charge on it.
        carriers_risk: B2B insurance: True = carrier's risk (Delhivery's insurance), False = owner's risk.
    """

    pickup_pincode: str
    delivery_pincode: str
    packages: Tuple[PackageCreate, ...]
    shipment_type: ShipmentType = ShipmentType.FORWARD
    is_blind_pickup: bool = False
    estimated_box_count: Optional[int] = None
    door_delivery: bool = False
    invoice_value: Decimal = Decimal("0")
    carriers_risk: bool = False


@dataclass(frozen=True)
class CostLine:
    """
    One pre-GST carrier cost line (e.g. Prime docket charge).

    Attributes:
        code: Stable machine code (FREIGHT, DOCKET, PICKUP, ODA, ODD_WEIGHT, DOOR_DELIVERY, MIN_LR_TOPUP).
        label: Plain-English label shown on the seller's breakup (after markup).
        amount: Carrier cost in rupees (Decimal, 2 dp).
    """

    code: str
    label: str
    amount: Decimal


@dataclass(frozen=True)
class CarrierLeg:
    """
    The carrier's pre-GST price for one leg.

    Attributes:
        kind: FORWARD, RTO or REVERSE.
        cost: Total pre-GST carrier cost of the leg (== sum of `lines`), excluding any carrier COD charge.
        lines: Cost breakup (one FREIGHT line for Delhivery).
        charged_weight_kg: The weight the carrier priced on.
        transit_days: Expected transit time, when known.
        source: LIVE / CACHED / TABLE / PROVISIONAL.
        fetched_at: When the price was obtained (naive UTC).
        details: Server-only provider details (Delhivery zone, charge_* map, gross; Prime lane id).
    """

    kind: CarrierLegKind
    cost: Decimal
    lines: Tuple[CostLine, ...]
    charged_weight_kg: Decimal
    transit_days: Optional[int]
    source: PriceSource
    fetched_at: datetime
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CarrierQuote:
    """
    One option's carrier-side answer.

    Attributes:
        option: The service option priced.
        serviceable: False → the card is greyed out with `unavailable_reason`.
        unavailable_code: Machine reason when not serviceable.
        unavailable_reason: Plain-English reason for the seller.
        forward: Forward (or reverse) leg; None when not serviceable.
        rto: Return-to-origin leg, when priced (Delhivery RTO call / Prime 100 % of forward).
        markup_percent: Logismart's markup on the carrier cost (Prime lane markup; Delhivery policy markup).
        cod_supported: Whether this option can carry COD at all (Prime: no COD at launch).
        snapshot: Server-only frozen rate data for re-pricing (Prime lane copy; Delhivery request inputs).
    """

    option: ServiceOption
    serviceable: bool
    unavailable_code: Optional[QuoteUnavailableCode] = None
    unavailable_reason: Optional[str] = None
    forward: Optional[CarrierLeg] = None
    rto: Optional[CarrierLeg] = None
    markup_percent: Decimal = Decimal("0")
    cod_supported: bool = True
    snapshot: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def unavailable(
        cls, option: ServiceOption, code: QuoteUnavailableCode, reason: str
    ) -> "CarrierQuote":
        """A greyed-out option card."""
        return cls(option=option, serviceable=False, unavailable_code=code, unavailable_reason=reason)
