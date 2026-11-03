"""
Ops carrier booking service (`GET/PUT /api/v1/shipments/{id}/carrier-billing`, DESIGN.md v4 D4 / Q13).

Ops book the parcel on `one.delhivery.com` and paste the Delhivery AWB, charged weight, and
charged amount here. When `charged_weight_kg` is provided, it is recorded as a
`MeasurementSource.CARRIER` measurement so the weight delta is passed through to the seller at
booking-time rates (Q8). `charged_amount` (incl. GST) is compared with what the seller was billed
on the pre-GST basis (GST is a pass-through): the difference is the shipment's margin, and a
billing gap (`has_gap`, `gap_amount`, `gap_message`) is flagged only on under-recovery.

Spring analogy: a `@Service` with `@Transactional` entry points for ops carrier reconciliation.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.money import is_billable_delta, money_to_float, to_money, to_weight
from app.core.permissions import assert_can_manage_shipments_or_pickups, is_tenant_staff
from app.models.pickups import (
    ActivityType,
    PickupRequest,
    ServiceOption,
    ShipmentActivity,
)
from app.models.repricing import ChargeAdjustmentReason, MeasurementSource
from app.models.tenants import Tenant, User, UserRole
from app.models.wallet import WalletTxnType
from app.repositories.delhivery_modules import DelhiveryModulesRepository
from app.schemas.v1.pricing import (
    AdminShipmentChargeCreate,
    CarrierBillingRead,
    CarrierBillingUpdate,
)
from app.services.delhivery_modules import DelhiveryModulesService
from app.services.pricing.sell_price import GST_PERCENT
from app.services.repricing import (
    ExtraBillCharge,
    MeasurementInput,
    RepriceChange,
    RepricingService,
)

CARRIER_BILLED_KEY = "carrier_billed"
PERCENT_BASE = Decimal(100)


@dataclass(frozen=True)
class MarginView:
    """Seller price vs carrier charge of one shipment, all amounts rounded to the paisa."""

    seller_billed: Decimal
    """`total_logistics_cost` (incl. GST)."""
    seller_taxable: Decimal
    """Seller price before GST."""
    charged: Decimal
    """Carrier charge entered by ops (incl. GST)."""
    carrier_taxable: Decimal
    """Carrier charge before GST."""
    margin: Decimal
    """`seller_taxable - carrier_taxable` (negative = under-recovery)."""


async def get_carrier_billing(
    session: AsyncSession,
    shipment_id: uuid.UUID,
    tenant_id: uuid.UUID,
    user: User,
) -> CarrierBillingRead:
    """
    Returns the carrier booking and invoice-gap view of a shipment (staff only).

    Raises:
        HTTPException(403): Caller is a customer.
        HTTPException(404): Shipment does not exist in this tenant.
    """
    _assert_staff_viewer(user)
    shipment = await RepricingService(session).load_shipment(shipment_id, tenant_id)
    return _build_carrier_billing_read(shipment)


async def update_carrier_billing(
    session: AsyncSession,
    shipment_id: uuid.UUID,
    tenant: Tenant,
    payload: CarrierBillingUpdate,
    user: User,
) -> CarrierBillingRead:
    """
    Saves the carrier AWB, optional charged weight (`CARRIER` measurement), and charged amount.

    Raises:
        HTTPException(403): Caller is a customer, read-only staff, or support staff.
        HTTPException(404): Shipment does not exist in this tenant.
        HTTPException(409): `carrier_awb` is already assigned to another shipment in this tenant.
    """
    _assert_staff_viewer(user)
    assert_can_manage_shipments_or_pickups(user, "record carrier billing")

    repricing = RepricingService(session)
    shipment = await repricing.load_shipment(shipment_id, tenant.id, for_update=True)
    await _assert_awb_unique(repricing, tenant.id, payload.carrier_awb, shipment.id)

    shipment.carrier_awb = payload.carrier_awb
    if payload.charged_weight_kg is not None:
        await _record_carrier_weight_if_changed(
            repricing, shipment, tenant, payload, user
        )

    _persist_carrier_billed(shipment, payload)
    await session.commit()
    return _build_carrier_billing_read(shipment)


async def apply_admin_shipment_charge(
    session: AsyncSession,
    shipment_id: uuid.UUID,
    tenant: Tenant,
    payload: AdminShipmentChargeCreate,
    user: User,
) -> CarrierBillingRead:
    """
    Applies an Owner/Admin bidirectional price override or charge adjustment (#558 3c, #568):
    - When `payload.override_total_price` is set: sets the new final billed price (incl. GST).
      If lower than current price -> credits difference back to customer's wallet + GST Credit Note.
      If higher than current price -> debits difference from customer's wallet + GST Debit Note.
    - When `payload.amount` is set: adds an extra charge on top of the current bill.
    """
    if user.role not in (UserRole.owner, UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Tenant Owners and Admins can adjust shipment charges.",
        )
    if payload.override_total_price is None and payload.amount is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either override_total_price or amount.",
        )
    repricing = RepricingService(session)
    shipment = await repricing.load_shipment(shipment_id, tenant.id, for_update=True)
    awb = shipment.tracking_id or str(shipment.id)[:8].upper()
    if payload.override_total_price is not None:
        target_total = to_money(payload.override_total_price)
        if target_total <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New final price must be greater than ₹0.",
            )
        old_bill = (
            to_money(shipment.payment_details.total_logistics_cost)
            if shipment.payment_details is not None
            else Decimal(0)
        )
        delta_preview = to_money(target_total - old_bill)
        direction_word = "credited" if delta_preview < 0 else "debited"
        change = RepriceChange(
            reason=ChargeAdjustmentReason.ADMIN_EDIT,
            override_total_price=target_total,
            remark=(
                f"Admin price override ({payload.label}) for {awb}: "
                f"₹{old_bill:.2f} → ₹{target_total:.2f} (₹{abs(delta_preview):.2f} {direction_word})"
            ),
        )
    else:
        raw_amount = to_money(payload.amount)
        gross_amount = (
            raw_amount
            if payload.includes_gst
            else to_money(raw_amount * (Decimal(1) + GST_PERCENT / PERCENT_BASE))
        )
        if gross_amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Charge adjustment amount must be greater than ₹0.",
            )
        change = RepriceChange(
            reason=ChargeAdjustmentReason.ADMIN_EDIT,
            extra_charge=ExtraBillCharge(
                amount=gross_amount,
                txn_type=WalletTxnType.SPEND,
                label=payload.label,
            ),
            remark=f"Admin charge adjustment ({payload.label}) for {awb}: +₹{gross_amount:.2f}",
        )
    result = await repricing.apply(shipment, tenant, change, actor=user)
    delta_sign = "+" if result.delta >= 0 else "-"
    note_label = "Credit Note" if result.delta < 0 else "Debit Note"
    activity = ShipmentActivity(
        pickup_id=shipment.id,
        user_id=user.id,
        activity_type=ActivityType.INFO_UPDATE,
        summary=(
            f"Admin Price Override: ₹{result.old_total:.2f} → ₹{result.new_total:.2f} "
            f"({delta_sign}₹{abs(result.delta):.2f}, {payload.label})"
        ),
        comment=(
            f"Bill adjusted from ₹{result.old_total:.2f} to ₹{result.new_total:.2f}"
            + (f" — {note_label} {result.note_number}" if result.note_number else "")
        ),
        is_public=True,
        diff={
            "payment_details.total_logistics_cost": {
                "old": money_to_float(result.old_total),
                "new": money_to_float(result.new_total),
            }
        },
    )
    session.add(activity)
    await session.commit()
    return _build_carrier_billing_read(shipment)


def _assert_staff_viewer(user: Optional[User]) -> None:
    """Rejects non-staff callers with 403."""
    if not is_tenant_staff(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required.",
        )


async def _assert_awb_unique(
    repricing: RepricingService,
    tenant_id: uuid.UUID,
    carrier_awb: str,
    shipment_id: uuid.UUID,
) -> None:
    """Raises 409 when another shipment in this tenant already uses `carrier_awb`."""
    conflict = await repricing.repo.find_shipment_by_carrier_awb(
        tenant_id, carrier_awb, exclude_shipment_id=shipment_id
    )
    if conflict is not None:
        label = conflict.tracking_id or str(conflict.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"AWB {carrier_awb} is already used by shipment {label}.",
        )


async def _record_carrier_weight_if_changed(
    repricing: RepricingService,
    shipment: PickupRequest,
    tenant: Tenant,
    payload: CarrierBillingUpdate,
    user: User,
) -> None:
    """Records a `CARRIER` measurement when `charged_weight_kg` differs from the active one."""
    target_kg = to_weight(payload.charged_weight_kg)
    active = await repricing.get_active_measurement(shipment.id, tenant.id)
    if (
        active is not None
        and active.source == MeasurementSource.CARRIER
        and to_weight(active.actual_weight_kg) == target_kg
    ):
        return
    result = await repricing.record_measurement(
        shipment,
        tenant,
        MeasurementInput(
            source=MeasurementSource.CARRIER,
            weight_only_kg=target_kg,
            remark=f"Carrier billed weight ({payload.carrier_awb})",
        ),
        actor=user,
    )
    if result.changed and not result.replayed:
        delhivery_service = DelhiveryModulesService(
            DelhiveryModulesRepository(repricing.session)
        )
        await delhivery_service.record_weight_audit_dispute(
            shipment=shipment,
            old_weight_kg=money_to_float(result.old_chargeable_weight),
            audited_weight_kg=money_to_float(result.new_chargeable_weight),
            old_total=money_to_float(result.old_total),
            new_total=money_to_float(result.new_total),
        )


def _persist_carrier_billed(
    shipment: PickupRequest, payload: CarrierBillingUpdate
) -> None:
    """Stores the ops-entered carrier billing values inside `payment_details.carrier_cost`."""
    payment = shipment.payment_details
    if payment is None:
        return
    record: Dict[str, Any] = dict(payment.carrier_cost or {})
    prev: Dict[str, Any] = dict(record.get(CARRIER_BILLED_KEY) or {})
    weight_kg = (
        float(to_weight(payload.charged_weight_kg))
        if payload.charged_weight_kg is not None
        else prev.get("charged_weight_kg")
    )
    charged_amount = (
        money_to_float(to_money(payload.charged_amount))
        if payload.charged_amount is not None
        else prev.get("charged_amount")
    )
    record[CARRIER_BILLED_KEY] = {
        "awb": payload.carrier_awb,
        "charged_weight_kg": weight_kg,
        "charged_amount": charged_amount,
    }
    payment.carrier_cost = record


def _carrier_taxable(charged_incl_gst: Decimal) -> Decimal:
    """
    Removes GST from the carrier's charge (ops enter Delhivery's amount incl. GST).

    Args:
        charged_incl_gst: What the carrier charged, GST included.

    Returns:
        The taxable (pre-GST) part, rounded to the paisa.
    """
    return to_money(charged_incl_gst / (Decimal(1) + GST_PERCENT / PERCENT_BASE))


def _seller_taxable_amount(payment: Any, seller_billed: Decimal) -> Decimal:
    """
    Seller price before GST, including the pre-GST portion of any GST-inclusive
    `bill_adjustments` added on top of the engine quote (note: `ADMIN_PRICE_OVERRIDE`
    already updates `payment.tax_amount` proportionally).
    """
    breakdown = getattr(payment, "pricing_breakdown", None) or {}
    adjustments = breakdown.get("bill_adjustments") or []
    adj_gross = sum(
        (
            to_money(a.get("amount"))
            for a in adjustments
            if isinstance(a, dict) and a.get("kind") != "ADMIN_PRICE_OVERRIDE"
        ),
        Decimal(0),
    )
    if adj_gross <= 0:
        return to_money(seller_billed - to_money(payment.tax_amount))
    engine_gross = to_money(seller_billed - adj_gross)
    engine_taxable = to_money(engine_gross - to_money(payment.tax_amount))
    adj_taxable = _carrier_taxable(adj_gross)
    return to_money(engine_taxable + adj_taxable)


def _margin_view(
    shipment: PickupRequest, charged_amount: Optional[float]
) -> Optional[MarginView]:
    """
    Builds the seller-vs-carrier comparison on the pre-GST basis (GST is a pass-through).

    Args:
        shipment: Shipment with its `payment_details` loaded.
        charged_amount: Carrier charge incl. GST entered by ops, or None.

    Returns:
        The margin view, or None before ops entered a charged amount.
    """
    payment = shipment.payment_details
    if charged_amount is None or payment is None:
        return None
    seller_billed = to_money(payment.total_logistics_cost)
    seller_taxable = _seller_taxable_amount(payment, seller_billed)
    charged = to_money(charged_amount)
    carrier_taxable = _carrier_taxable(charged)
    return MarginView(
        seller_billed=seller_billed,
        seller_taxable=seller_taxable,
        charged=charged,
        carrier_taxable=carrier_taxable,
        margin=to_money(seller_taxable - carrier_taxable),
    )


def _gap_verdict(view: Optional[MarginView]) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Flags under-recovery only: the carrier charged more (pre-GST) than the seller paid us.

    A positive margin (e.g. the Prime markup) is the expected outcome and never an alert.

    Returns:
        (has_gap, under-recovered amount or 0.0 / None, message or None).
    """
    if view is None:
        return False, None, None
    shortfall = to_money(-view.margin)
    if shortfall <= 0 or not is_billable_delta(shortfall):
        return False, 0.0, None
    return (
        True,
        money_to_float(shortfall),
        (
            f"Carrier charged ₹{view.carrier_taxable:.2f} + GST vs ₹{view.seller_taxable:.2f} + GST "
            f"billed to the seller: ₹{shortfall:.2f} not recovered."
        ),
    )


def shipment_transporter_name(shipment: PickupRequest) -> Optional[str]:
    """
    Returns the Prime lane's `transporter_name` from `payment_details.carrier_cost.snapshot`
    (staff-only; never exposed to customers).
    """
    payment = shipment.payment_details
    if payment is None or not isinstance(payment.carrier_cost, dict):
        return None
    snapshot = payment.carrier_cost.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    raw = snapshot.get("transporter_name")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _build_carrier_billing_read(shipment: PickupRequest) -> CarrierBillingRead:
    """Builds the `CarrierBillingRead` response without exposing `carrier_cost`."""
    payment = shipment.payment_details
    billed: Dict[str, Any] = (
        dict((payment.carrier_cost or {}).get(CARRIER_BILLED_KEY) or {})
        if payment is not None
        else {}
    )
    charged_weight_kg = (
        float(to_weight(billed["charged_weight_kg"]))
        if billed.get("charged_weight_kg") is not None
        else None
    )
    charged_amount = (
        money_to_float(to_money(billed["charged_amount"]))
        if billed.get("charged_amount") is not None
        else None
    )
    view = _margin_view(shipment, charged_amount)
    has_gap, gap_amount, gap_message = _gap_verdict(view)
    gap_gross_amount = (
        money_to_float(to_money(Decimal(str(gap_amount)) * (Decimal(1) + GST_PERCENT / PERCENT_BASE)))
        if has_gap and gap_amount is not None and gap_amount > 0
        else (0.0 if gap_amount is not None else None)
    )
    return CarrierBillingRead(
        service_option=shipment.service_option or ServiceOption.DELHIVERY_SURFACE,
        carrier_awb=shipment.carrier_awb,
        charged_weight_kg=charged_weight_kg,
        charged_amount=charged_amount,
        has_gap=has_gap,
        gap_amount=gap_amount,
        gap_gross_amount=gap_gross_amount,
        gap_message=gap_message,
        seller_billed_amount=(
            money_to_float(payment.total_logistics_cost) if payment is not None else None
        ),
        seller_billed_taxable=money_to_float(view.seller_taxable) if view else None,
        carrier_charged_taxable=money_to_float(view.carrier_taxable) if view else None,
        margin_amount=money_to_float(view.margin) if view else None,
        transporter_name=shipment_transporter_name(shipment),
    )
