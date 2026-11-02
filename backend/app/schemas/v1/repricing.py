"""
HTTP request / response models for re-pricing on change (plan Phase B, item B8).

Spring Boot analogy: these are the `@RequestBody` / response DTOs of the re-pricing
`@RestController`. They carry no business rules: every price, wallet and GST decision
is made by `app.services.repricing.RepricingService` (reprice-core) and the shipment /
manifest services (reprice-integration). The `from_*` class methods only map the
service dataclasses onto the JSON contract agreed with the UI (board #95, #103).

Money fields are `Decimal` internally and serialised as JSON numbers (rupees, 2 dp)
so the frontend only formats them (Zero Frontend Math).
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer, WithJsonSchema, model_validator

from app.models.pickups import FreightPaymentMode
from app.models.repricing import ChargeAdjustmentReason, MeasurementSource
from app.schemas.v1.pickups import PackageCreate, PickupRead

MAX_EVIDENCE_URLS = 3
"""A pickup / hub measurement carries at most 3 photos (plan B5)."""
MAX_REMARK_LENGTH = 255
"""Matches `shipment_measurements.remark VARCHAR(255)`."""
MAX_EVIDENCE_URL_LENGTH = 2048
"""Defensive bound on a single evidence URL."""
MAX_WEIGHT_ONLY_KG = 100_000.0
"""Same upper bound as the NDR `measured_weight_kg` field."""
MEASUREMENT_SOURCES_FOR_API = (
    MeasurementSource.PICKUP,
    MeasurementSource.HUB,
    MeasurementSource.ADMIN,
)
"""CLAIM measurements are created only by an accepted weight claim, never directly over HTTP."""
ALLOWED_EVIDENCE_SCHEMES = ("https://", "http://")

Money = Annotated[
    Decimal,
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
    WithJsonSchema({"type": "number"}),
]
"""Rupee amount: exact Decimal in Python, JSON number on the wire."""
Weight = Annotated[
    Decimal,
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
    WithJsonSchema({"type": "number"}),
]
"""Kilograms (3 dp): exact Decimal in Python, JSON number on the wire."""


class SettlementAction(str, Enum):
    """How a price change is settled, from the merchant's point of view (UI contract)."""

    DEBIT = "DEBIT"
    REFUND = "REFUND"
    COLLECTIBLE = "COLLECTIBLE"
    NONE = "NONE"


class RejectionRule(str, Enum):
    """Which rule refused a field in a preview (plan §2.0 H-rules, B9; mirrors `RepricingError.rule`)."""

    ZERO_QUOTE = "H-7"
    SERVICE_TYPE_LOCKED = "H-8"
    COLLECTIBLE_FROZEN = "H-9"
    OUT_FOR_DELIVERY_LOCK = "H-12"
    MERCHANT_EDIT_MATRIX = "B9"
    MEASUREMENT = "MEASUREMENT"
    STATE = "STATE"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def validate_evidence_urls(urls: List[str]) -> List[str]:
    """
    Strips blanks and checks every evidence URL is an http(s) link.

    Args:
        urls: Raw URLs from the request.

    Returns:
        The cleaned list.

    Raises:
        ValueError: a URL is not http(s) or is too long.
    """
    cleaned = [url.strip() for url in urls if url and url.strip()]
    for url in cleaned:
        if not url.lower().startswith(ALLOWED_EVIDENCE_SCHEMES):
            raise ValueError(f"evidence_urls must be http(s) links: '{url}'")
        if len(url) > MAX_EVIDENCE_URL_LENGTH:
            raise ValueError("evidence_urls entries must be at most 2048 characters")
    return cleaned


class MeasurementCreate(BaseModel):
    """
    Body of `POST /shipments/{id}/measurements` (staff: rider at pickup, hub, admin).

    Send exactly one of:
    - `packages`: the full measured parcel (box count, L x B x H + unit, weight + unit), or
    - `weight_kg`: a weight-only hub entry (the declared box sizes are kept and their
      weights are scaled to this total by the re-pricing service).
    """

    source: MeasurementSource = MeasurementSource.HUB
    packages: Optional[List[PackageCreate]] = Field(default=None, min_length=1)
    weight_kg: Optional[float] = Field(default=None, gt=0, le=MAX_WEIGHT_ONLY_KG)
    override_total_price: Optional[float] = Field(
        default=None,
        gt=0,
        le=10_000_000.0,
        description="Optional Admin final price override (₹ incl. GST; #568).",
    )
    evidence_urls: List[str] = Field(default_factory=list, max_length=MAX_EVIDENCE_URLS)
    remark: Optional[str] = Field(default=None, max_length=MAX_REMARK_LENGTH)

    @model_validator(mode="after")
    def _exactly_one_basis(self) -> "MeasurementCreate":
        """Enforces the packages / weight_kg exclusivity, the source allow-list and clean URLs."""
        has_packages = bool(self.packages)
        has_weight = self.weight_kg is not None
        if has_packages == has_weight:
            raise ValueError("Send exactly one of 'packages' or 'weight_kg'.")
        if self.source not in MEASUREMENT_SOURCES_FOR_API:
            raise ValueError("source must be PICKUP, HUB or ADMIN.")
        self.evidence_urls = validate_evidence_urls(self.evidence_urls)
        if self.remark is not None:
            self.remark = self.remark.strip() or None
        return self


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

NO_CHANGE_MESSAGE = "No change to the shipping charges."
"""Settlement text when the change does not move any money."""
_SETTLEMENT_ACTION_BY_KIND = {
    "WALLET_DEBIT": SettlementAction.DEBIT,
    "WALLET_REFUND": SettlementAction.REFUND,
    "COLLECTIBLE_CHANGE": SettlementAction.COLLECTIBLE,
    "RECORD_ONLY": SettlementAction.NONE,
    "NONE": SettlementAction.NONE,
}
"""reprice-core `SettlementKind` value -> UI settlement action."""
_NOTE_LABELS = {"DEBIT_NOTE": "debit note", "CREDIT_NOTE": "credit note"}


def _enum_value(value: Any) -> Any:
    """Returns `.value` for enums, the value itself otherwise."""
    return value.value if isinstance(value, Enum) else value


def _format_inr(amount: Decimal) -> str:
    """Formats a rupee amount for a message, e.g. `₹1,234.50` (display text only, no arithmetic)."""
    return f"₹{abs(amount):,.2f}"


def _settlement_message(action: SettlementAction, wallet_delta: Decimal, preview: Any) -> str:
    """
    Human-readable settlement line for the preview dialog (Delhivery One wallet wording).

    Args:
        action: Mapped settlement action.
        wallet_delta: Signed merchant-view wallet movement from the service.
        preview: The service preview (for the note type and collectible amounts).

    Returns:
        One sentence; the amounts are the service's numbers, only formatted here.
    """
    note = _NOTE_LABELS.get(_enum_value(preview.note_type) or "", "")
    note_suffix = f" with a GST {note}" if note else ""
    if action == SettlementAction.DEBIT:
        return f"{_format_inr(wallet_delta)} will be deducted from the wallet{note_suffix}."
    if action == SettlementAction.REFUND:
        return f"{_format_inr(wallet_delta)} will be refunded to the wallet{note_suffix}."
    if action == SettlementAction.COLLECTIBLE:
        return (
            "Freight to collect at delivery becomes "
            f"{_format_inr(Decimal(preview.new_freight_collectible))}."
        )
    return NO_CHANGE_MESSAGE


class RejectedField(BaseModel):
    """One field the server refused in a preview (shown next to that input in the dialog)."""

    field: Optional[str] = None
    rule: RejectionRule
    message: str

    @classmethod
    def from_error(cls, error: Any) -> "RejectedField":
        """
        Maps a reprice-core `RepricingError` (an HTTPException with `.rule` and `.field`).

        Args:
            error: The raised error.

        Returns:
            The rejection row; unknown rules are reported as STATE.
        """
        raw_rule = getattr(error, "rule", None)
        rule = (
            RejectionRule(raw_rule)
            if raw_rule in RejectionRule._value2member_map_
            else RejectionRule.STATE
        )
        field = getattr(error, "field", None)
        return cls(
            field=str(_enum_value(field)) if field is not None else None,
            rule=rule,
            message=str(getattr(error, "detail", "") or "This change is not allowed."),
        )


class RepricePreviewResponse(BaseModel):
    """
    Result of `POST /shipments/{id}/reprice-preview`: what saving the change would do.
    Nothing is written. Refusals come back as 200 with `rejected_fields` filled in.
    """

    shipment_id: UUID
    reason: Optional[ChargeAdjustmentReason] = None
    old_total: Money
    new_total: Money
    delta: Money
    old_chargeable_weight: Weight
    new_chargeable_weight: Weight
    new_pricing_breakdown: dict = Field(default_factory=dict)
    freight_payment_mode: Optional[FreightPaymentMode] = None
    settlement_action: SettlementAction = SettlementAction.NONE
    wallet_delta: Money = Decimal("0.00")
    note_type: Optional[str] = None
    settlement_message: str = ""
    old_cod_collectible: Money = Decimal("0.00")
    new_cod_collectible: Money = Decimal("0.00")
    old_freight_collectible: Money = Decimal("0.00")
    new_freight_collectible: Money = Decimal("0.00")
    collectible_frozen: bool = False
    price_changed: bool = False
    warnings: List[str] = Field(default_factory=list)
    rejected_fields: List[RejectedField] = Field(default_factory=list)

    @classmethod
    def from_preview(cls, preview: Any) -> "RepricePreviewResponse":
        """
        Maps reprice-core's `RepricePreview` dataclass onto the HTTP contract.

        Args:
            preview: `app.services.repricing.RepricePreview` (duck-typed to keep this
                module free of a service import).

        Returns:
            The response model, with no rejections.
        """
        action = _SETTLEMENT_ACTION_BY_KIND.get(_enum_value(preview.settlement), SettlementAction.NONE)
        wallet_delta = Decimal(preview.wallet_delta)
        return cls(
            shipment_id=preview.shipment_id,
            reason=preview.reason,
            old_total=preview.old_total,
            new_total=preview.new_total,
            delta=preview.delta,
            old_chargeable_weight=preview.old_chargeable_weight,
            new_chargeable_weight=preview.new_chargeable_weight,
            new_pricing_breakdown=dict(preview.new_breakdown or {}),
            freight_payment_mode=preview.freight_payment_mode,
            settlement_action=action,
            wallet_delta=wallet_delta,
            note_type=preview.note_type,
            settlement_message=_settlement_message(action, wallet_delta, preview),
            old_cod_collectible=preview.old_cod_amount,
            new_cod_collectible=preview.new_cod_amount,
            old_freight_collectible=preview.old_freight_collectible,
            new_freight_collectible=preview.new_freight_collectible,
            collectible_frozen=bool(preview.collectible_frozen),
            price_changed=bool(preview.changed),
            warnings=list(preview.warnings or ()),
        )

    @classmethod
    def unchanged(
        cls,
        shipment_id: UUID,
        total: Decimal,
        chargeable_weight: Decimal,
        breakdown: Optional[dict],
        rejected: Optional[List[RejectedField]] = None,
    ) -> "RepricePreviewResponse":
        """
        A preview where nothing would change (no price input in the body, or every
        field was refused): totals stay as persisted.

        Args:
            shipment_id: The shipment.
            total: Current `total_logistics_cost`.
            chargeable_weight: Current chargeable weight.
            breakdown: Current pricing breakdown.
            rejected: Refused fields, if any.

        Returns:
            The response model with `price_changed=False`.
        """
        return cls(
            shipment_id=shipment_id,
            old_total=total,
            new_total=total,
            delta=Decimal("0.00"),
            old_chargeable_weight=chargeable_weight,
            new_chargeable_weight=chargeable_weight,
            new_pricing_breakdown=dict(breakdown or {}),
            settlement_message=NO_CHANGE_MESSAGE,
            rejected_fields=list(rejected or []),
        )


class ChargeAdjustmentRead(BaseModel):
    """One row of the charges history (`shipment_charge_adjustments`)."""

    id: UUID
    created_at: datetime
    reason: ChargeAdjustmentReason
    old_total: Money
    new_total: Money
    delta: Money
    old_chargeable_weight: Optional[Weight] = None
    new_chargeable_weight: Optional[Weight] = None
    freight_payment_mode: FreightPaymentMode
    wallet_txn_id: Optional[UUID] = None
    billing_invoice_id: Optional[UUID] = None
    note_number: Optional[str] = None
    note_type: Optional[str] = None
    actor_email: Optional[str] = None

    model_config = {"from_attributes": True}


class MeasurementResult(BaseModel):
    """Response of `POST /shipments/{id}/measurements`: the re-priced shipment plus its adjustment row."""

    shipment: PickupRead
    adjustment: Optional[ChargeAdjustmentRead] = None
