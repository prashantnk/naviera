"""
Pricing redesign API schemas (DESIGN.md v4; contract `llm_resources/.agents/pricing/API_CONTRACT.md`).

- `PricingPolicy*`: the staff-only selling policy stored in `tenant.settings["pricing_policy"]`
  (markups, Logismart COD fee, enabled options). Replaces the old `pricing_config` rate card.
- `Quote*`: `POST /api/v1/quotes` option cards (Delhivery Surface / Express, Logismart Prime).
- `Valuation*`: `POST /api/v1/shipments/valuation` (D-06: the declared total is server-computed).
- `CarrierBilling*`: the ops AWB / charged weight / amount form (staff only).

Money is a JSON number in rupees (2 dp), always computed by the backend (Zero Frontend Math).
Spring analogy: request/response DTOs validated with Bean Validation annotations.
"""

from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.manifests import ServiceFlow
from app.models.pickups import FreightPaymentMode, ServiceOption, ShipmentType
from app.schemas.v1.pickups import (
    PINCODE_PATTERN,
    PackageCreate,
    assert_packages_have_dimensions,
)
from app.schemas.v1.tenant_settings import (
    COD_FEE_MIN_MAX,
    COD_FEE_PERCENT_MAX,
    MARKUP_PERCENT_MAX,
    OptionMarkup,
)
from app.services.pricing.types import QuoteUnavailableCode

AMOUNT_MAX = 100_000_000.0
CARRIER_AWB_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]{3,39}$"
ALL_SERVICE_OPTIONS: List[ServiceOption] = list(ServiceOption)


# --- Pricing policy ---------------------------------------------------------------


class _PricingPolicyFields(BaseModel):
    """The editable policy fields (shared by the write and read models)."""

    delhivery_markup_percent: float = Field(default=0.0, ge=0, le=MARKUP_PERCENT_MAX)
    prime_default_markup_percent: float = Field(default=20.0, ge=0, le=MARKUP_PERCENT_MAX)
    cod_fee_percent: Optional[float] = Field(default=None, ge=0, le=COD_FEE_PERCENT_MAX)
    cod_fee_min: Optional[float] = Field(default=None, ge=0, le=COD_FEE_MIN_MAX)
    enabled_options: List[ServiceOption] = Field(default_factory=lambda: list(ALL_SERVICE_OPTIONS))
    option_markups: Dict[ServiceOption, OptionMarkup] = Field(default_factory=dict)
    """
    Per-option markup rule (PERCENT of the carrier cost or a FLAT ₹ per shipment leg).
    A missing option keeps the default: `delhivery_markup_percent` for Delhivery options,
    each Prime lane's own markup % for PRIME_SURFACE. Stored and returned as set.
    """

    @field_validator("enabled_options")
    @classmethod
    def _dedupe_options(cls, value: List[ServiceOption]) -> List[ServiceOption]:
        """Keeps each option once, in enum order."""
        return [option for option in ServiceOption if option in set(value)]


class PricingPolicy(_PricingPolicyFields):
    """
    Logismart's selling policy (staff-only). Percentages are plain percents (20 = 20 %).
    COD stays OFF until BOTH `cod_fee_percent` and `cod_fee_min` are set (fail closed).
    """

    model_config = ConfigDict(extra="forbid")

    @property
    def cod_enabled(self) -> bool:
        """True only when the admin has set both COD fee values."""
        return self.cod_fee_percent is not None and self.cod_fee_min is not None


class PricingPolicyRead(_PricingPolicyFields):
    """`GET /api/v1/pricing/policy` (staff)."""

    cod_enabled: bool = False
    delhivery_configured: bool = False
    """False → Delhivery options show 'price unavailable' (no API token for this tenant yet)."""
    delhivery_b2b_configured: bool = False
    """False → the Delhivery B2B Cargo option shows 'not connected' (no B2B login for this tenant yet)."""


# --- Quotes -----------------------------------------------------------------------


class QuoteRequest(BaseModel):
    """The exact booking inputs that change the price (A-03: quote == booking inputs)."""

    service_flow: ServiceFlow
    shipment_type: ShipmentType = ShipmentType.FORWARD
    pickup_pincode: str = Field(pattern=PINCODE_PATTERN)
    delivery_pincode: str = Field(pattern=PINCODE_PATTERN)
    packages: List[PackageCreate] = Field(default_factory=list)
    is_blind_pickup: bool = False
    estimated_box_count: Optional[int] = Field(default=None, gt=0)
    freight_payment_mode: FreightPaymentMode = FreightPaymentMode.PREPAID
    is_cod: bool = False
    cod_amount: float = Field(default=0.0, ge=0, le=AMOUNT_MAX)
    add_shipping_to_cod: bool = False
    shipment_value: float = Field(default=0.0, ge=0, le=AMOUNT_MAX)
    shipment_tax_value: float = Field(default=0.0, ge=0, le=AMOUNT_MAX)
    door_delivery: bool = False
    is_carriers_risk: bool = False
    """B2B insurance: carrier's risk (Delhivery's insurance) vs owner's risk; prices Delhivery B2B ROV."""

    @field_validator("packages")
    @classmethod
    def _dims_required(cls, value: List[PackageCreate]) -> List[PackageCreate]:
        """A-26: every declared box needs length, breadth and height > 0."""
        assert_packages_have_dimensions(value)
        return value


class SellLine(BaseModel):
    """One line of the seller's price breakup (pre-GST, plus the GST line)."""

    code: str
    label: str
    amount: float


class QuoteOption(BaseModel):
    """One option card."""

    service_option: ServiceOption
    serviceable: bool
    unavailable_code: Optional[QuoteUnavailableCode] = None
    unavailable_reason: Optional[str] = None
    total_amount: float = 0.0
    freight_amount: float = 0.0
    cod_fee: float = 0.0
    tax_amount: float = 0.0
    chargeable_weight_kg: float = 0.0
    transit_days: Optional[int] = None
    expected_delivery_date: Optional[date] = None
    sell_lines: List[SellLine] = Field(default_factory=list)
    door_collectible_amount: float = 0.0
    cod_remittance_amount: float = 0.0
    priced_from_cache: bool = False
    price_age_minutes: Optional[int] = None


class QuoteResponse(BaseModel):
    """`POST /api/v1/quotes` answer."""

    shipment_total_value: float
    eway_bill_required: bool
    eway_bill_threshold: float
    cod_available: bool
    cod_unavailable_reason: Optional[str] = None
    heavy_weight_warning: bool = False
    heavy_weight_threshold_kg: float
    options: List[QuoteOption]


# --- Valuation (D-06) -------------------------------------------------------------


class ValuationRequest(BaseModel):
    """Goods value split as typed by the seller."""

    shipment_value: float = Field(default=0.0, ge=0, le=AMOUNT_MAX)
    shipment_tax_value: float = Field(default=0.0, ge=0, le=AMOUNT_MAX)


class ValuationResponse(BaseModel):
    """Server-computed declared total and the e-way bill rule it triggers."""

    shipment_total_value: float
    eway_bill_required: bool
    eway_bill_threshold: float


# --- Carrier billing (ops) --------------------------------------------------------


class CarrierBillingUpdate(BaseModel):
    """What ops copy from one.delhivery.com after booking the parcel there (Q13)."""

    carrier_awb: str = Field(pattern=CARRIER_AWB_PATTERN)
    charged_weight_kg: Optional[float] = Field(default=None, gt=0, le=100_000)
    charged_amount: Optional[float] = Field(default=None, ge=0, le=AMOUNT_MAX)

    @field_validator("carrier_awb", mode="before")
    @classmethod
    def _trim_awb(cls, value: object) -> object:
        """Trims pasted whitespace before the pattern check."""
        return value.strip() if isinstance(value, str) else value


class CarrierBillingRead(BaseModel):
    """The ops view of the carrier booking, the shipment margin and the gap flag (staff only)."""

    service_option: ServiceOption
    carrier_awb: Optional[str] = None
    charged_weight_kg: Optional[float] = None
    charged_amount: Optional[float] = None
    """Carrier charge incl. GST, as entered by ops."""
    has_gap: bool = False
    """True only on under-recovery: the carrier charged more (pre-GST) than the seller paid."""
    gap_amount: Optional[float] = None
    """Under-recovered amount (pre-GST); 0.0 when no gap, None before a charge is entered."""
    gap_gross_amount: Optional[float] = None
    """Under-recovered amount incl. 18% GST (`gap_amount * 1.18`), ready for 1-click recovery."""
    gap_message: Optional[str] = None
    seller_billed_amount: Optional[float] = None
    """What the seller was billed (`total_logistics_cost`, incl. GST)."""
    seller_billed_taxable: Optional[float] = None
    """Seller price before GST (None before a carrier charge is entered)."""
    carrier_charged_taxable: Optional[float] = None
    """Carrier charge before GST."""
    margin_amount: Optional[float] = None
    """`seller_billed_taxable - carrier_charged_taxable`; negative = loss."""
    transporter_name: Optional[str] = None
    """Prime transporter name from the lane snapshot (staff only; None for Delhivery)."""


class AdminShipmentChargeCreate(BaseModel):
    """
    Owner/Admin bidirectional shipment price override or charge adjustment (#558 3c, #568).
    Supports either:
    - `override_total_price`: sets the new final billed price (₹ incl. GST), crediting the
      customer's wallet + GST Credit Note when lower than the current bill, or debiting the
      customer's wallet + GST Debit Note when higher; OR
    - `amount`: adds an extra charge (₹) on top of the current bill.
    """

    model_config = ConfigDict(extra="forbid")

    override_total_price: Optional[float] = Field(
        default=None,
        gt=0.0,
        le=AMOUNT_MAX,
        description="New final total shipment price in INR (incl. 18% GST). Credits wallet if lower, debits if higher.",
    )
    amount: Optional[float] = Field(
        default=None,
        gt=0.0,
        le=AMOUNT_MAX,
        description="Additional charge in INR (GST-inclusive when includes_gst=True, else pre-GST).",
    )
    includes_gst: bool = Field(
        default=True,
        description="True when `amount` already includes 18% GST; False to add 18% GST on top.",
    )
    label: str = Field(
        default="Admin price adjustment",
        min_length=2,
        max_length=120,
        description="Short label / reason recorded on the bill adjustment, wallet ledger, and GST Credit/Debit Note.",
    )

    @field_validator("label", mode="before")
    @classmethod
    def _strip_label(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

