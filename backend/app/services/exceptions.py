"""
Delivery Exceptions / NDR business service (Delhivery One parity).

Merchants act on on-hold shipments; ops / admins raise exceptions through the
shipment status update (see `ShipmentService.update_shipment`). Every action
is validated against the server-side allowed-actions matrix
(`services/ndr_rules.py`), resolves or advances the shipment status and writes
an immutable `ShipmentActivity`.

Spring Boot Equivalent: '@Service @Transactional class ExceptionsService'.
"""

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.money import ZERO_MONEY, money_to_float, to_money
from app.core.permissions import (
    assert_can_accept_shipment_charges,
    assert_not_read_only,
    is_tenant_staff,
)
from app.models.delhivery_modules import InvoiceNoteType
from app.models.exceptions import ExceptionCategory
from app.models.manifests import ServiceFlow
from app.models.pickups import (
    ActivityType,
    Address,
    NdrAction,
    NdrExceptionReason,
    PickupDocument,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
    ShipmentType,
)
from app.models.repricing import ChargeAdjustmentReason, MeasurementSource
from app.models.tenants import Tenant, User, UserRole
from app.models.wallet import WalletTxnType
from app.repositories.delhivery_modules import DelhiveryModulesRepository
from app.repositories.exceptions import (
    NDR_ACTION_DIFF_KEY,
    ExceptionShipment,
    ExceptionsRepository,
)
from app.repositories.shipments import ShipmentRepository
from app.repositories.wallet import WalletRepository
from app.schemas.v1.exceptions import (
    BulkActionFailure,
    BulkNdrActionRequest,
    BulkNdrActionResponse,
    ExceptionCategoryCount,
    ExceptionConsignee,
    ExceptionListResponse,
    ExceptionPaymentMode,
    ExceptionRow,
    ExceptionSummaryResponse,
    NdrActionRequest,
)
from app.schemas.v1.pickups import NdrExceptionResolveRequest
from app.services import ndr_rules
from app.services.delhivery_modules import DelhiveryModulesService, tenant_gst_rate
from app.services.repricing import ExtraBillCharge, MeasurementInput, RepriceChange
from app.services.shipment import ShipmentService
from app.services.shipment_lifecycle import ShipmentLifecycleMachine
from app.services.wallet import WalletService

SECONDS_PER_DAY = 86_400
EWAY_BILL_PATTERN = re.compile(r"^\d{12}$")
ALLOWED_DOCUMENT_URL_SCHEMES = ("http", "https")
DEFAULT_RESCHEDULE_OFFSET = timedelta(days=1)
LIABILITY_WAIVER_REASONS = frozenset(
    {NdrExceptionReason.DAMAGED, NdrExceptionReason.SHORT_SHIPMENT}
)
"""Exceptions where "Logismart liable" waives the RTO charge (plan B6, decision D51)."""
GST_INCLUSIVE_CHARGE_REASONS = frozenset({NdrExceptionReason.FREIGHT_COLLECTION})
"""Ops enter these charges GST-inclusive; every other exception charge is GST-exclusive (D55)."""
LIABILITY_WAIVER_STAFF_ONLY_DETAIL = (
    "Only Logismart staff can mark Logismart as liable for this return."
)
FREIGHT_COLLECTION_LABEL = "Freight collection"
MANUAL_WEIGHT_CHARGE_LABEL = "Measured weight charge"

LEGACY_ACTION_ALIASES: Dict[str, NdrAction] = {
    "DELIVER_WITHOUT_APPOINTMENT": NdrAction.DELIVER_WITHOUT_APPOINTMENT,
    "UPDATE_CONSIGNEE_DETAILS": NdrAction.UPDATE_CONSIGNEE,
    "RETURN_TO_SENDER": NdrAction.RETURN_TO_ORIGIN,
    "HOLD_SHIPMENT": NdrAction.HOLD,
}
"""Free-text actions accepted by the legacy `POST /shipments/{id}/resolve-exception`."""

ACTION_SUMMARIES: Dict[NdrAction, str] = {
    NdrAction.REATTEMPT: "Reattempt requested",
    NdrAction.RETURN_TO_ORIGIN: "Return to origin (RTO) requested",
    NdrAction.UPDATE_CONSIGNEE: "Consignee details updated",
    NdrAction.UPDATE_PAYMENT_MODE: "Payment mode updated",
    NdrAction.UPDATE_EWAY_BILL: "E-way bill updated",
    NdrAction.UPLOAD_DOCUMENT: "Document uploaded",
    NdrAction.BOOK_APPOINTMENT: "Delivery appointment booked",
    NdrAction.DELIVER_WITHOUT_APPOINTMENT: "Deliver without appointment authorised",
    NdrAction.PARTIAL_DELIVERY: "Partial delivery authorised",
    NdrAction.HOLD: "Hold until all boxes arrive",
    NdrAction.REPACK_AND_DELIVER: "Repack and deliver authorised",
    NdrAction.ACKNOWLEDGE_CHARGES: "Charges acknowledged",
    NdrAction.ACCEPT_WEIGHT: "Measured weight accepted",
    NdrAction.DISPUTE_WEIGHT: "Measured weight disputed",
    NdrAction.RESCHEDULE_PICKUP: "Pickup rescheduled",
    NdrAction.CANCEL_PICKUP: "Pickup cancelled",
}


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (matches TIMESTAMP columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enum_value(value: Any) -> Any:
    """JSON-friendly enum value (or the raw value)."""
    return value.value if hasattr(value, "value") else value


@dataclass
class _ActionContext:
    """Everything an action handler needs."""

    shipment: PickupRequest
    request: NdrActionRequest
    actor: User
    tenant: Tenant
    is_b2b: bool
    held_from: Optional[PickupStatus] = None
    """Status when the current exception was raised (None = unknown / legacy row)."""


@dataclass
class _ActionOutcome:
    """What a handler decided; applied atomically by `_finalize_action`."""

    new_status: Optional[PickupStatus]
    summary: str
    diff: Dict[str, Any] = field(default_factory=dict)
    new_pickup_address: Optional[Address] = None
    new_delivery_address: Optional[Address] = None
    documents_to_add: List[PickupDocument] = field(default_factory=list)
    waive_rto_charge: bool = False


ActionHandler = Callable[[_ActionContext], Awaitable[_ActionOutcome]]


class ExceptionsService:
    """Lists, summarises and resolves on-hold shipments."""

    def __init__(
        self,
        repo: ExceptionsRepository,
        shipment_service: ShipmentService,
        wallet_service: WalletService,
    ):
        self.repo = repo
        self.shipment_service = shipment_service
        self.wallet_service = wallet_service
        self.session = repo.session
        self._handlers: Dict[NdrAction, ActionHandler] = {
            NdrAction.REATTEMPT: self._handle_reattempt,
            NdrAction.RETURN_TO_ORIGIN: self._handle_return_to_origin,
            NdrAction.UPDATE_CONSIGNEE: self._handle_update_consignee,
            NdrAction.UPDATE_PAYMENT_MODE: self._handle_update_payment_mode,
            NdrAction.UPDATE_EWAY_BILL: self._handle_update_eway_bill,
            NdrAction.UPLOAD_DOCUMENT: self._handle_upload_document,
            NdrAction.BOOK_APPOINTMENT: self._handle_book_appointment,
            NdrAction.DELIVER_WITHOUT_APPOINTMENT: self._handle_deliver_without_appointment,
            NdrAction.PARTIAL_DELIVERY: self._handle_partial_delivery,
            NdrAction.REPACK_AND_DELIVER: self._handle_resume,
            NdrAction.HOLD: self._handle_awaiting_ops,
            NdrAction.DISPUTE_WEIGHT: self._handle_awaiting_ops,
            NdrAction.ACKNOWLEDGE_CHARGES: self._handle_acknowledge_charges,
            NdrAction.ACCEPT_WEIGHT: self._handle_accept_weight,
            NdrAction.RESCHEDULE_PICKUP: self._handle_reschedule_pickup,
            NdrAction.CANCEL_PICKUP: self._handle_cancel_pickup,
        }

    # ------------------------------------------------------------------ reads

    @staticmethod
    def _scoped_user_id(user: User) -> Optional[uuid.UUID]:
        """Customers only ever see their own shipments; tenant staff see the tenant."""
        return user.id if user.role == UserRole.customer else None

    @staticmethod
    def _is_actionable(
        allowed: List[NdrAction], awaiting_ops: bool, shipment_status: PickupStatus
    ) -> bool:
        """A row is actionable while on hold, with actions left, and not waiting on ops."""
        return bool(allowed) and not awaiting_ops and shipment_status == PickupStatus.EXCEPTION

    async def get_summary(
        self, *, tenant_id: uuid.UUID, user: User, service_flow: ServiceFlow
    ) -> ExceptionSummaryResponse:
        """
        Counts per group (B2C) / category (B2B), split into actionable vs non-actionable.
        """
        is_b2b = service_flow == ServiceFlow.B2B
        facets = await self.repo.list_facets(
            tenant_id=tenant_id, is_b2b=is_b2b, user_id=self._scoped_user_id(user)
        )
        totals: Dict[ExceptionCategory, int] = {}
        actionable_totals: Dict[ExceptionCategory, int] = {}
        actionable_count = 0
        for facet in facets:
            allowed = ndr_rules.allowed_actions(
                facet.ndr_reason, facet.shipment_type, is_b2b, facet.held_from
            )
            actionable = self._is_actionable(allowed, facet.awaiting_ops, PickupStatus.EXCEPTION)
            actionable_count += int(actionable)
            category = ndr_rules.categorize(
                facet.ndr_reason, facet.shipment_type, is_b2b, actionable, facet.held_from
            )
            if category is None:
                continue
            totals[category] = totals.get(category, 0) + 1
            actionable_totals[category] = actionable_totals.get(category, 0) + int(actionable)

        categories = [
            ExceptionCategoryCount(
                category=category,
                label=ndr_rules.CATEGORY_LABELS[category],
                total=totals.get(category, 0),
                actionable=actionable_totals.get(category, 0),
            )
            for category in ndr_rules.FLOW_CATEGORIES[service_flow]
        ]
        return ExceptionSummaryResponse(
            service_flow=service_flow,
            total=len(facets),
            actionable=actionable_count,
            non_actionable=len(facets) - actionable_count,
            categories=categories,
        )

    @staticmethod
    def _validate_category(
        service_flow: ServiceFlow, category: Optional[ExceptionCategory]
    ) -> None:
        """Rejects categories that don't belong to the requested flow."""
        if category is not None and category not in ndr_rules.FLOW_CATEGORIES[service_flow]:
            valid = ", ".join(c.value for c in ndr_rules.FLOW_CATEGORIES[service_flow])
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category {category.value} is not valid for {service_flow.value}. Use one of: {valid}.",
            )

    async def list_exceptions(
        self,
        *,
        tenant_id: uuid.UUID,
        user: User,
        service_flow: ServiceFlow,
        category: Optional[ExceptionCategory],
        actionable_only: bool,
        search: Optional[str],
        page: int,
        size: int,
    ) -> ExceptionListResponse:
        """
        Paginated on-hold shipments with server-computed actions, attempts and aging.
        """
        self._validate_category(service_flow, category)
        is_b2b = service_flow == ServiceFlow.B2B
        reasons = (
            ndr_rules.b2b_category_reasons(category)
            if is_b2b and category is not None
            else None
        )
        records = await self.repo.list_exception_shipments(
            tenant_id=tenant_id,
            is_b2b=is_b2b,
            user_id=self._scoped_user_id(user),
            search=search,
            reasons=reasons,
        )
        now = _utc_now_naive()
        gst_rate = await self._tenant_gst_fraction(tenant_id)
        rows = [self._build_row(record, now, gst_rate) for record in records]
        if category is not None:
            rows = [row for row in rows if row.category == category]
        if actionable_only:
            rows = [row for row in rows if row.is_actionable]

        total = len(rows)
        start = (page - 1) * size
        return ExceptionListResponse(
            items=rows[start : start + size],
            total=total,
            page=page,
            size=size,
            pages=math.ceil(total / size) if size > 0 else 0,
        )

    @staticmethod
    def customer_side_address(shipment: PickupRequest) -> Address:
        """Consignee for forward shipments; the pickup customer for reverse (NPR)."""
        if shipment.shipment_type == ShipmentType.REVERSE:
            return shipment.pickup_address
        return shipment.delivery_address

    @staticmethod
    def _aging_days(shipment: PickupRequest, now: datetime) -> int:
        """Whole days since the current exception was raised (server-side aging)."""
        raised_at = shipment.exception_raised_at or shipment.updated_at or shipment.created_at
        if raised_at.tzinfo is not None:
            raised_at = raised_at.astimezone(timezone.utc).replace(tzinfo=None)
        return max(0, int((now - raised_at).total_seconds() // SECONDS_PER_DAY))

    @staticmethod
    def _box_count(shipment: PickupRequest) -> int:
        """Declared cartons (blind pickups) or the sum of package box counts."""
        if shipment.is_blind_pickup:
            return int(shipment.estimated_box_count or 0)
        return sum(int(pkg.box_count or 0) for pkg in shipment.packages or [])

    async def _tenant_gst_fraction(self, tenant_id: uuid.UUID) -> Decimal:
        """The tenant's GST rate as a Decimal fraction (one lookup per list/action)."""
        tenant = await self.session.get(Tenant, tenant_id)
        return Decimal(str(tenant_gst_rate(tenant)))

    @staticmethod
    def charge_amount_payable(
        shipment: PickupRequest, gst_rate: Decimal
    ) -> Optional[float]:
        """
        The wallet debit the shipper consents to when accepting the exception charge (A-20).

        FREIGHT_COLLECTION is entered GST-inclusive and billed as entered; ADDITIONAL_CHARGES
        and a manual WEIGHT_DISCREPANCY charge are entered GST-exclusive (D55), so GST is added.

        Args:
            shipment: The on-hold shipment.
            gst_rate: Tenant GST as a fraction (e.g. 0.18).

        Returns:
            The GST-inclusive amount, or None when no charge is recorded.
        """
        amount = to_money(shipment.charge_amount)
        if amount <= ZERO_MONEY:
            return None
        reason = ndr_rules.canonical_reason(shipment.ndr_reason)
        if reason in GST_INCLUSIVE_CHARGE_REASONS:
            return money_to_float(amount)
        return money_to_float(to_money(amount * (Decimal(1) + gst_rate)))

    def _build_row(
        self, record: ExceptionShipment, now: datetime, gst_rate: Decimal
    ) -> ExceptionRow:
        """Maps a loaded shipment onto the exceptions grid DTO."""
        shipment = record.shipment
        is_on_hold = shipment.status == PickupStatus.EXCEPTION
        allowed = (
            ndr_rules.allowed_actions(
                shipment.ndr_reason, shipment.shipment_type, record.is_b2b, record.held_from
            )
            if is_on_hold
            else []
        )
        actionable = self._is_actionable(allowed, record.awaiting_ops, shipment.status)
        party = self.customer_side_address(shipment)
        payment = shipment.payment_details
        is_cod = bool(payment and payment.is_cod)
        appointment_start = shipment.appointment_start
        return ExceptionRow(
            shipment_id=shipment.id,
            tracking_id=shipment.tracking_id,
            order_reference_id=shipment.order_reference_id,
            service_flow=ndr_rules.flow_of(record.is_b2b),
            shipment_type=shipment.shipment_type,
            status=shipment.status,
            ndr_reason=shipment.ndr_reason,
            category=(
                ndr_rules.categorize(
                    shipment.ndr_reason,
                    shipment.shipment_type,
                    record.is_b2b,
                    actionable,
                    record.held_from,
                )
                if is_on_hold
                else None
            ),
            is_actionable=actionable,
            awaiting_ops=record.awaiting_ops and is_on_hold,
            allowed_actions=allowed if actionable else [],
            attempts=int(shipment.ndr_attempt_count or 0),
            max_attempts=ndr_rules.MAX_NDR_ATTEMPTS,
            last_remark=shipment.ndr_remark,
            exception_raised_at=shipment.exception_raised_at,
            aging_days=self._aging_days(shipment, now) if is_on_hold else 0,
            consignee=ExceptionConsignee(
                name=party.name,
                phone=party.phone,
                address_line1=party.address_line1,
                address_line2=party.address_line2,
                landmark=party.landmark,
                city=party.city,
                state=party.state,
                pincode=party.pincode,
            ),
            origin_city=shipment.pickup_address.city,
            destination_city=shipment.delivery_address.city,
            payment_mode=ExceptionPaymentMode.COD if is_cod else ExceptionPaymentMode.PREPAID,
            freight_payment_mode=payment.freight_payment_mode if payment else None,
            cod_amount=float(payment.cod_amount) if is_cod and payment else 0.0,
            charge_amount=shipment.charge_amount,
            charge_amount_payable=self.charge_amount_payable(shipment, gst_rate),
            logismart_liable_allowed=(
                is_on_hold
                and NdrAction.RETURN_TO_ORIGIN in allowed
                and ndr_rules.canonical_reason(shipment.ndr_reason) in LIABILITY_WAIVER_REASONS
            ),
            box_count=self._box_count(shipment),
            pdd=appointment_start.date() if appointment_start else None,
            appointment_start=appointment_start,
            appointment_end=shipment.appointment_end,
            created_at=shipment.created_at,
        )

    # ---------------------------------------------------------------- actions

    async def _load_owned_shipment(
        self, shipment_id: uuid.UUID, user: User, tenant_id: uuid.UUID
    ) -> ExceptionShipment:
        """Tenant + ownership guard (404 to avoid ID enumeration)."""
        record = await self.repo.get_exception_shipment(shipment_id, tenant_id)
        owner_id = self._scoped_user_id(user)
        if record is None or (
            owner_id is not None and record.shipment.created_by_user_id != owner_id
        ):
            raise HTTPException(status_code=404, detail="Shipment not found")
        return record

    @staticmethod
    def _assert_action_allowed(record: ExceptionShipment, action: NdrAction) -> None:
        """Validates the action against status, awaiting-ops state and the matrix."""
        shipment = record.shipment
        if shipment.status != PickupStatus.EXCEPTION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Shipment {shipment.tracking_id} has no active exception (status {shipment.status.value}).",
            )
        if record.awaiting_ops:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your response is already recorded; this exception is now with the operations team.",
            )
        allowed = ndr_rules.allowed_actions(
            shipment.ndr_reason, shipment.shipment_type, record.is_b2b, record.held_from
        )
        if action not in allowed:
            reason = shipment.ndr_reason.value if shipment.ndr_reason else "UNKNOWN"
            allowed_text = ", ".join(a.value for a in allowed) or "none"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Action {action.value} is not allowed for a {reason} exception on this shipment. Allowed: {allowed_text}.",
            )

    @staticmethod
    def _assert_liability_flag_allowed(request: NdrActionRequest, user: User) -> None:
        """
        A-09: only tenant staff may waive an RTO charge as "Logismart liable"; a shipper
        sending the flag through the API is refused (it was a self-waiver loophole).

        Raises:
            HTTPException(403): a non-staff actor sent `logismart_liable=true`.
        """
        if request.logismart_liable and not is_tenant_staff(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=LIABILITY_WAIVER_STAFF_ONLY_DETAIL,
            )

    async def _apply_action_no_commit(
        self,
        shipment_id: uuid.UUID,
        request: NdrActionRequest,
        user: User,
        tenant: Tenant,
    ) -> PickupRequest:
        """
        Validates and applies one action inside the caller's transaction.

        The shipment row is locked first, so concurrent actions on the same
        shipment serialise and the loser re-validates against the resolved state
        (a double-clicked charge acknowledgement fails with 400 instead of
        debiting twice). Actions that cost the shipper money or change the door
        collection (A-22) need the shipment owner or a Tenant Owner/Admin.
        """
        self._assert_liability_flag_allowed(request, user)
        await self.repo.lock_shipment_row(shipment_id, tenant.id)
        record = await self._load_owned_shipment(shipment_id, user, tenant.id)
        self._assert_action_allowed(record, request.action)
        needs_consent = request.action in ndr_rules.CONSENT_ACTIONS
        if needs_consent:
            self._assert_can_consent_to_charges(record.shipment, user)
        context = _ActionContext(
            shipment=record.shipment,
            request=request,
            actor=user,
            tenant=tenant,
            is_b2b=record.is_b2b,
            held_from=record.held_from,
        )
        outcome = await self._handlers[request.action](context)
        if needs_consent:
            outcome.diff["charge_accepted_by"] = self._consent_audit(record.shipment, user)
        return await self._finalize_action(context, outcome)

    @staticmethod
    def _assert_can_consent_to_charges(shipment: PickupRequest, user: User) -> None:
        """D30 / A-22: only the shipment's owner or a Tenant Owner/Admin may consent."""
        assert_can_accept_shipment_charges(
            user,
            is_shipment_owner=shipment.created_by_user_id == user.id,
            action=f"accept charges, start an RTO or change the payment mode on shipment {shipment.tracking_id}",
        )

    @staticmethod
    def _consent_audit(shipment: PickupRequest, user: User) -> Dict[str, Any]:
        """Who consented to a wallet debit (logged in the activity diff)."""
        return {
            "user_id": str(user.id),
            "email": user.email,
            "role": _enum_value(user.role),
            "on_behalf_of_shipper": shipment.created_by_user_id != user.id,
        }

    async def apply_action(
        self,
        *,
        shipment_id: uuid.UUID,
        request: NdrActionRequest,
        user: User,
        tenant: Tenant,
    ) -> ExceptionRow:
        """Applies one merchant action atomically and returns the refreshed row."""
        assert_not_read_only(user, "apply exception actions")
        await self._apply_action_no_commit(shipment_id, request, user, tenant)
        await self.session.commit()
        record = await self.repo.get_exception_shipment(shipment_id, tenant.id)
        if record is None:
            raise HTTPException(status_code=404, detail="Shipment not found")
        return self._build_row(
            record, _utc_now_naive(), Decimal(str(tenant_gst_rate(tenant)))
        )

    async def apply_bulk_action(
        self, *, request: BulkNdrActionRequest, user: User, tenant: Tenant
    ) -> BulkNdrActionResponse:
        """
        Applies one action to many shipments. Each shipment runs in its own
        SAVEPOINT, so failures are reported individually without rolling back
        the successful ones.
        """
        assert_not_read_only(user, "apply bulk exception actions")
        if request.action not in ndr_rules.BULK_ACTIONS:
            allowed_text = ", ".join(sorted(a.value for a in ndr_rules.BULK_ACTIONS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bulk action supports only: {allowed_text}.",
            )
        succeeded: List[uuid.UUID] = []
        failed: List[BulkActionFailure] = []
        for shipment_id in dict.fromkeys(request.shipment_ids):
            try:
                async with self.session.begin_nested():
                    await self._apply_action_no_commit(
                        shipment_id, NdrActionRequest(action=request.action), user, tenant
                    )
                succeeded.append(shipment_id)
            except HTTPException as exc:
                failed.append(BulkActionFailure(shipment_id=shipment_id, reason=str(exc.detail)))
        await self.session.commit()
        return BulkNdrActionResponse(succeeded=succeeded, failed=failed)

    async def resolve_legacy(
        self,
        *,
        shipment_id: uuid.UUID,
        payload: NdrExceptionResolveRequest,
        user: User,
        tenant: Tenant,
    ) -> PickupRequest:
        """
        Backward-compatible `POST /shipments/{id}/resolve-exception`: maps the
        legacy free-text action onto `NdrAction` and runs the same pipeline
        (read-only guard + D30 charge-consent rule included).
        """
        assert_not_read_only(user, "resolve exceptions")
        action = self._map_legacy_action(payload.action)
        request = NdrActionRequest(
            action=action,
            is_cod=payload.is_cod,
            eway_bill_number=payload.eway_bill_number,
            consignee_phone=payload.consignee_phone,
            consignee_address_line1=payload.consignee_address_line1,
            notes=payload.notes,
        )
        shipment = await self._apply_action_no_commit(shipment_id, request, user, tenant)
        await self.session.commit()
        return shipment

    @staticmethod
    def _map_legacy_action(raw_action: str) -> NdrAction:
        """Legacy alias or any NdrAction value (case-insensitive) -> NdrAction."""
        key = (raw_action or "").strip().upper()
        if key in LEGACY_ACTION_ALIASES:
            return LEGACY_ACTION_ALIASES[key]
        try:
            return NdrAction(key)
        except ValueError:
            supported = sorted(set(LEGACY_ACTION_ALIASES) | {a.value for a in NdrAction})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported action '{raw_action}'. Supported: {', '.join(supported)}.",
            )

    async def _finalize_action(
        self, context: _ActionContext, outcome: _ActionOutcome
    ) -> PickupRequest:
        """
        Applies the outcome: status transition, exception-field cleanup, the
        audit activity and (for cancellations) the prepaid-freight refund.
        """
        shipment = context.shipment
        old_status = shipment.status
        old_reason = _enum_value(shipment.ndr_reason)
        diff: Dict[str, Any] = {NDR_ACTION_DIFF_KEY: context.request.action.value, **outcome.diff}
        if context.request.notes:
            diff["notes"] = context.request.notes

        new_status = outcome.new_status
        if new_status is not None and new_status != old_status:
            ShipmentLifecycleMachine.validate_transition(old_status, new_status)
            shipment.status = new_status
            shipment.ndr_reason = None
            shipment.exception_raised_at = None
            shipment.charge_amount = None
            diff["status"] = {"old": old_status.value, "new": new_status.value}
            diff["ndr_reason"] = {"old": old_reason, "new": None}
            diff.update(self.shipment_service.ensure_delivery_otp(shipment))
            if new_status == PickupStatus.CANCELLED:
                diff.update(self.shipment_service.release_for_cancellation(shipment))
            elif new_status == PickupStatus.RTO_INITIATED:
                diff.update(
                    await self.shipment_service.apply_rto_charges(
                        shipment,
                        context.tenant.id,
                        actor=context.actor,
                        waive_rto_charge=outcome.waive_rto_charge,
                    )
                )
        shipment.updated_at = _utc_now_naive()

        activity = ShipmentActivity(
            pickup_id=shipment.id,
            user_id=context.actor.id,
            activity_type=(
                ActivityType.STATUS_CHANGE if "status" in diff else ActivityType.INFO_UPDATE
            ),
            summary=f"{outcome.summary} ({context.request.action.value})",
            comment=context.request.notes or outcome.summary,
            is_public=True,
            diff=diff,
        )
        updated = await self.shipment_service.shipment_repo.update_shipment_with_activity(
            shipment=shipment,
            activity=activity,
            packages_to_add=[],
            packages_to_delete=[],
            documents_to_add=outcome.documents_to_add,
            documents_to_delete=[],
            new_pickup_address=outcome.new_pickup_address,
            new_delivery_address=outcome.new_delivery_address,
        )
        if new_status == PickupStatus.CANCELLED and old_status != PickupStatus.CANCELLED:
            await self.shipment_service.refund_prepaid_freight(
                updated, context.tenant.id, actor=context.actor
            )
        return updated

    # --------------------------------------------------------- handler helpers

    @staticmethod
    def _resume_status(context: _ActionContext) -> PickupStatus:
        """Where the shipment goes once the merchant resolves the exception (D-04)."""
        shipment = context.shipment
        return ndr_rules.resume_status(
            shipment.ndr_reason,
            shipment.shipment_type,
            shipment.manifest_id is not None,
            context.held_from,
        )

    @staticmethod
    def _has_consignee_edit(request: NdrActionRequest) -> bool:
        """True when the request carries any customer-side contact / address change."""
        return any(
            value is not None
            for value in (
                request.consignee_name,
                request.consignee_phone,
                request.consignee_address_line1,
                request.consignee_address_line2,
                request.landmark,
            )
        )

    def _build_consignee_snapshot(
        self, shipment: PickupRequest, request: NdrActionRequest
    ) -> Tuple[Address, Dict[str, Any]]:
        """
        Creates a fresh, unsaved address snapshot of the customer-side party with
        the requested edits. Edits must stay within the SAME pincode.

        Raises:
            HTTPException(400): the pincode would change.
        """
        current = self.customer_side_address(shipment)
        requested_pin = (request.consignee_pincode or "").strip()
        if requested_pin and requested_pin != current.pincode:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Address can only be updated within the same pincode ({current.pincode}). "
                    "For a different pincode, return the shipment and book a new one."
                ),
            )

        def _pick(new_value: Optional[str], old_value: Optional[str]) -> Optional[str]:
            return new_value.strip() if new_value is not None and new_value.strip() else old_value

        snapshot = Address(
            tenant_id=shipment.tenant_id,
            user_id=current.user_id,
            category=current.category,
            scope=current.scope,
            name=_pick(request.consignee_name, current.name) or current.name,
            company_name=current.company_name,
            email=current.email,
            gstin=current.gstin,
            alternate_phone=current.alternate_phone,
            phone=_pick(request.consignee_phone, current.phone) or current.phone,
            address_line1=_pick(request.consignee_address_line1, current.address_line1)
            or current.address_line1,
            address_line2=_pick(request.consignee_address_line2, current.address_line2),
            landmark=_pick(request.landmark, current.landmark),
            city=current.city,
            state=current.state,
            pincode=current.pincode,
            country=current.country,
            is_saved=False,
        )
        changes = {
            key: {"old": getattr(current, key), "new": getattr(snapshot, key)}
            for key in (
                "name",
                "phone",
                "address_line1",
                "address_line2",
                "landmark",
            )
            if getattr(current, key) != getattr(snapshot, key)
        }
        return snapshot, changes

    def _apply_consignee_edit(
        self, context: _ActionContext, outcome: _ActionOutcome
    ) -> None:
        """Attaches a same-pincode address snapshot to the outcome (forward: delivery, reverse: pickup)."""
        snapshot, changes = self._build_consignee_snapshot(context.shipment, context.request)
        outcome.diff["consignee"] = changes
        if context.shipment.shipment_type == ShipmentType.REVERSE:
            outcome.new_pickup_address = snapshot
        else:
            outcome.new_delivery_address = snapshot

    def _attempt_limit_outcome(self, context: _ActionContext) -> Optional[_ActionOutcome]:
        """Forces RTO / cancellation when a retry is requested past the attempt limit."""
        shipment = context.shipment
        forced = ndr_rules.attempt_limit_outcome(
            shipment.ndr_reason,
            shipment.shipment_type,
            shipment.ndr_attempt_count,
            context.held_from,
        )
        if forced is None:
            return None
        label = "Auto-RTO" if forced == PickupStatus.RTO_INITIATED else "Auto-cancelled"
        return _ActionOutcome(
            new_status=forced,
            summary=f"{label}: maximum {ndr_rules.MAX_NDR_ATTEMPTS} attempts reached",
            diff={"ndr_auto_resolution": forced.value},
        )

    @staticmethod
    def _require(value: Any, message: str) -> Any:
        """400 when a field required by the chosen action is missing."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        return value

    # ---------------------------------------------------------------- handlers

    async def _handle_reattempt(self, context: _ActionContext) -> _ActionOutcome:
        """Reattempt delivery (optionally with same-pincode contact / address edits)."""
        limit_outcome = self._attempt_limit_outcome(context)
        if limit_outcome is not None:
            return limit_outcome
        outcome = _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.REATTEMPT],
        )
        if self._has_consignee_edit(context.request):
            self._apply_consignee_edit(context, outcome)
        if context.request.preferred_date is not None:
            outcome.diff["preferred_date"] = context.request.preferred_date.isoformat()
        return outcome

    async def _handle_return_to_origin(self, context: _ActionContext) -> _ActionOutcome:
        """
        Return the shipment to the merchant (RTO). On a DAMAGED / SHORT_SHIPMENT exception
        a staff-confirmed "Logismart liable" flag waives the RTO charge (plan B6, D51); the
        flag from a shipper is refused earlier (A-09).
        """
        waive = (
            bool(context.request.logismart_liable)
            and is_tenant_staff(context.actor)
            and ndr_rules.canonical_reason(context.shipment.ndr_reason) in LIABILITY_WAIVER_REASONS
        )
        outcome = _ActionOutcome(
            new_status=PickupStatus.RTO_INITIATED,
            summary=ACTION_SUMMARIES[NdrAction.RETURN_TO_ORIGIN],
            waive_rto_charge=waive,
        )
        if waive:
            outcome.diff["rto_charge_waived"] = {"reason": "Logismart liable"}
        return outcome

    async def _handle_update_consignee(self, context: _ActionContext) -> _ActionOutcome:
        """Update phone / address (same pincode) and reattempt."""
        if not self._has_consignee_edit(context.request):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide consignee_phone, consignee_address_line1, consignee_address_line2 or landmark.",
            )
        outcome = _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.UPDATE_CONSIGNEE],
        )
        self._apply_consignee_edit(context, outcome)
        return outcome

    async def _handle_update_payment_mode(self, context: _ActionContext) -> _ActionOutcome:
        """
        Switch between COD and prepaid collection at the door (DO1 Payment Dispute). The
        COD fee is re-priced through RepricingService: wallet delta + DEBIT/CREDIT_NOTE for
        wallet-billed shipments; on TO_PAY the freight stays collectible either way (B7).
        """
        is_cod = self._require(context.request.is_cod, "is_cod is required to update the payment mode.")
        payment = context.shipment.payment_details
        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This shipment has no payment details to update.",
            )
        goods = to_money(payment.shipment_total_value) if is_cod else ZERO_MONEY
        if is_cod and goods <= ZERO_MONEY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="COD needs a shipment value greater than 0.",
            )
        old_mode = {"is_cod": payment.is_cod, "cod_amount": payment.cod_amount}
        result = await self.shipment_service.reprice_no_commit(
            context.shipment,
            context.tenant,
            RepriceChange(
                reason=ChargeAdjustmentReason.PAYMENT_MODE_CHANGE,
                is_cod=bool(is_cod),
                cod_amount=goods,
            ),
            context.actor,
        )
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.UPDATE_PAYMENT_MODE],
            diff={
                "payment_mode": {
                    "old": old_mode,
                    "new": {"is_cod": payment.is_cod, "cod_amount": payment.cod_amount},
                },
                **result.activity_diff(),
            },
        )

    async def _handle_update_eway_bill(self, context: _ActionContext) -> _ActionOutcome:
        """Record a (12-digit) e-way bill and optional invoice number."""
        eway = self._require(
            context.request.eway_bill_number, "eway_bill_number is required."
        ).strip()
        if not EWAY_BILL_PATTERN.match(eway):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid E-Way bill format: '{eway}'. Must be exactly 12 digits.",
            )
        payment = context.shipment.payment_details
        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This shipment has no payment details to attach an e-way bill to.",
            )
        eway_bills = list(payment.eway_bill_numbers or [])
        if eway not in eway_bills:
            eway_bills.append(eway)
        payment.eway_bill_numbers = eway_bills
        diff: Dict[str, Any] = {"eway_bill_numbers": {"new": eway_bills}}
        invoice = (context.request.invoice_number or "").strip()
        if invoice:
            invoices = list(payment.invoice_numbers or [])
            if invoice not in invoices:
                invoices.append(invoice)
            payment.invoice_numbers = invoices
            diff["invoice_numbers"] = {"new": invoices}
        self.session.add(payment)
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.UPDATE_EWAY_BILL],
            diff=diff,
        )

    async def _handle_upload_document(self, context: _ActionContext) -> _ActionOutcome:
        """Attach a document reference (type + http(s) URL)."""
        doc_type = self._require(context.request.document_type, "document_type is required.")
        url = self._require(context.request.document_url, "document_url is required.").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ALLOWED_DOCUMENT_URL_SCHEMES or not parsed.netloc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="document_url must be an http(s) URL.",
            )
        file_name = parsed.path.rsplit("/", 1)[-1] or f"{doc_type.value.lower()}_document"
        document = PickupDocument(
            pickup_id=context.shipment.id,
            document_type=doc_type,
            file_url=url,
            file_name=file_name,
        )
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.UPLOAD_DOCUMENT],
            diff={"documents": {"added": [file_name], "document_type": doc_type.value}},
            documents_to_add=[document],
        )

    async def _handle_book_appointment(self, context: _ActionContext) -> _ActionOutcome:
        """Book a delivery appointment slot."""
        start = self._require(context.request.appointment_start, "appointment_start is required.")
        end = self._require(context.request.appointment_end, "appointment_end is required.")
        shipment = context.shipment
        diff = {
            "appointment_start": {
                "old": shipment.appointment_start.isoformat() if shipment.appointment_start else None,
                "new": start.isoformat(),
            },
            "appointment_end": {
                "old": shipment.appointment_end.isoformat() if shipment.appointment_end else None,
                "new": end.isoformat(),
            },
        }
        shipment.appointment_start = start
        shipment.appointment_end = end
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.BOOK_APPOINTMENT],
            diff=diff,
        )

    async def _handle_resume(self, context: _ActionContext) -> _ActionOutcome:
        """Actions that simply release the hold (partial, repack)."""
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[context.request.action],
        )

    async def _handle_deliver_without_appointment(
        self, context: _ActionContext
    ) -> _ActionOutcome:
        """
        Release an APPOINTMENT_NEEDED hold without a slot (D-08). The expired window is
        cleared (recorded as a waiver), otherwise the worker would put the parcel back on
        hold every 5 minutes for the same expired appointment.
        """
        shipment = context.shipment
        diff: Dict[str, Any] = {}
        if shipment.appointment_start is not None or shipment.appointment_end is not None:
            diff["appointment_waived"] = {
                "start": shipment.appointment_start.isoformat() if shipment.appointment_start else None,
                "end": shipment.appointment_end.isoformat() if shipment.appointment_end else None,
            }
            shipment.appointment_start = None
            shipment.appointment_end = None
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.DELIVER_WITHOUT_APPOINTMENT],
            diff=diff,
        )

    async def _handle_partial_delivery(self, context: _ActionContext) -> _ActionOutcome:
        """
        Short shipment: deliver the boxes that arrived (DO1 "Attempt partial delivery").
        Records `delivered_box_count`, optionally re-prices a revised goods COD (COD fee
        re-priced with a DN/CN), and opens a loss ticket for the missing boxes (plan B6).
        """
        shipment = context.shipment
        request = context.request
        outcome = _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.PARTIAL_DELIVERY],
        )
        declared_boxes = self._box_count(shipment)
        if request.delivered_box_count is not None:
            outcome.diff["delivered_box_count"] = {
                "old": shipment.delivered_box_count,
                "new": request.delivered_box_count,
                "declared": declared_boxes,
            }
            shipment.delivered_box_count = request.delivered_box_count
        payment = shipment.payment_details
        if request.revised_cod_amount is not None and payment is not None and payment.is_cod:
            result = await self.shipment_service.reprice_no_commit(
                shipment,
                context.tenant,
                RepriceChange(
                    reason=ChargeAdjustmentReason.SHORT_SHIPMENT,
                    cod_amount=to_money(request.revised_cod_amount),
                ),
                context.actor,
            )
            outcome.diff.update(result.activity_diff())
        delivered = request.delivered_box_count
        if delivered is not None and delivered < declared_boxes:
            ticket_number = await self._delhivery_service().open_short_shipment_ticket(
                shipment=shipment,
                actor=context.actor,
                delivered_boxes=delivered,
                declared_boxes=declared_boxes,
            )
            if ticket_number:
                outcome.diff["loss_ticket"] = ticket_number
        return outcome

    def _delhivery_service(self) -> DelhiveryModulesService:
        """GST notes and support tickets share the caller's transaction."""
        return DelhiveryModulesService(DelhiveryModulesRepository(self.session))

    async def _handle_awaiting_ops(self, context: _ActionContext) -> _ActionOutcome:
        """HOLD / DISPUTE_WEIGHT: stays on hold, now non-actionable until ops respond."""
        return _ActionOutcome(
            new_status=None,
            summary=ACTION_SUMMARIES[context.request.action],
        )

    async def _handle_acknowledge_charges(self, context: _ActionContext) -> _ActionOutcome:
        """
        The merchant accepts a charge entered by ops, then the hold is released.

        - FREIGHT_COLLECTION: outstanding freight (GST included). It goes into the bill through
          RepricingService: wallet debit + DEBIT_NOTE; on TO_PAY the freight to collect at the
          door falls by the same amount (plan B3).
        - ADDITIONAL_CHARGES (Mathadi / union): entered GST-exclusive (D55), GST added, debited
          as a separate charge outside the bill with its own DEBIT_NOTE; never refunded by a cancel.
        """
        shipment = context.shipment
        reason = ndr_rules.canonical_reason(shipment.ndr_reason)
        txn_type = ndr_rules.CHARGE_TXN_TYPES.get(reason) if reason else None
        amount = to_money(shipment.charge_amount)
        if txn_type is None or amount <= ZERO_MONEY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No charge amount is recorded on this exception.",
            )
        if txn_type == WalletTxnType.FREIGHT_COLLECTION:
            result = await self.shipment_service.reprice_no_commit(
                shipment,
                context.tenant,
                RepriceChange(
                    reason=ChargeAdjustmentReason.FREIGHT_COLLECTION,
                    extra_charge=ExtraBillCharge(
                        amount=amount,
                        txn_type=WalletTxnType.FREIGHT_COLLECTION,
                        label=FREIGHT_COLLECTION_LABEL,
                    ),
                ),
                context.actor,
            )
            return _ActionOutcome(
                new_status=self._resume_status(context),
                summary=f"{ACTION_SUMMARIES[NdrAction.ACKNOWLEDGE_CHARGES]}: INR {amount:.2f} debited",
                diff={
                    "wallet_debit": {"txn_type": txn_type.value, "amount": money_to_float(amount)},
                    **result.activity_diff(),
                },
            )
        gross = self._gst_inclusive(amount, context.tenant)
        txn = await self.wallet_service.debit_exception_charge(
            user_id=shipment.created_by_user_id,
            tenant=context.tenant,
            shipment=shipment,
            amount=money_to_float(gross),
            txn_type=txn_type,
            is_b2b=context.is_b2b,
        )
        note = await self._delhivery_service().record_shipment_billing_note(
            shipment=shipment,
            note_type=InvoiceNoteType.DEBIT_NOTE.value,
            amount_override=money_to_float(gross),
            is_b2b=context.is_b2b,
            is_separate_charge=True,
        )
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=f"{ACTION_SUMMARIES[NdrAction.ACKNOWLEDGE_CHARGES]}: INR {gross:.2f} debited",
            diff={
                "wallet_debit": {
                    "txn_type": txn_type.value,
                    "amount_excl_gst": money_to_float(amount),
                    "amount": money_to_float(gross),
                    "receipt_number": txn.receipt_number,
                    "note_number": note.invoice_number if note else None,
                }
            },
        )

    @staticmethod
    def _gst_inclusive(amount: Decimal, tenant: Tenant) -> Decimal:
        """Adds the tenant's GST to an ops-entered, GST-exclusive charge (D55)."""
        return to_money(amount * (Decimal(1) + Decimal(str(tenant_gst_rate(tenant)))))

    async def _handle_accept_weight(self, context: _ActionContext) -> _ActionOutcome:
        """
        Accept the measured weight. With an ops-measured weight it is a weight-only hub
        measurement (declared box sizes kept, re-billed both ways). Otherwise the ops-entered
        weight charge (GST-exclusive, D55) goes into the bill as a manual weight charge,
        with a DEBIT_NOTE on wallet-billed shipments (plan B3).
        """
        shipment = context.shipment
        raise_details = (
            await self.repo.get_latest_raise_details(shipment.id, shipment.tenant_id) or {}
        )
        measured = raise_details.get("measured_weight_kg")
        diff: Dict[str, Any] = {}
        if isinstance(measured, (int, float)) and measured > 0:
            result = await self.shipment_service.measure_no_commit(
                shipment,
                context.tenant,
                MeasurementInput(
                    source=MeasurementSource.HUB, weight_only_kg=to_money(measured)
                ),
                context.actor,
            )
            diff = {**self.shipment_service.weight_audit_diff(result), **result.activity_diff()}
        elif shipment.charge_amount and float(shipment.charge_amount) > 0:
            gross = self._gst_inclusive(to_money(shipment.charge_amount), context.tenant)
            result = await self.shipment_service.reprice_no_commit(
                shipment,
                context.tenant,
                RepriceChange(
                    reason=ChargeAdjustmentReason.MANUAL_WEIGHT_CHARGE,
                    extra_charge=ExtraBillCharge(
                        amount=gross,
                        txn_type=WalletTxnType.WEIGHT_AUDIT_DEBIT,
                        label=MANUAL_WEIGHT_CHARGE_LABEL,
                    ),
                ),
                context.actor,
            )
            if result.changed and not result.replayed:
                await self._delhivery_service().record_weight_audit_dispute(
                    shipment=shipment,
                    old_weight_kg=money_to_float(result.old_chargeable_weight),
                    audited_weight_kg=money_to_float(result.new_chargeable_weight),
                    old_total=money_to_float(result.old_total),
                    new_total=money_to_float(result.new_total),
                )
            diff = result.activity_diff()
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.ACCEPT_WEIGHT],
            diff=diff,
        )

    async def _handle_reschedule_pickup(self, context: _ActionContext) -> _ActionOutcome:
        """Reschedule a failed pickup (auto-cancel once the attempt limit is reached)."""
        shipment = context.shipment
        limit_outcome = self._attempt_limit_outcome(context)
        if limit_outcome is not None:
            return limit_outcome
        today = datetime.now(timezone.utc).date()
        new_date: date = context.request.preferred_date or (today + DEFAULT_RESCHEDULE_OFFSET)
        if new_date < today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="preferred_date cannot be in the past.",
            )
        diff = {
            "requested_pickup_date": {
                "old": shipment.requested_pickup_date.isoformat(),
                "new": new_date.isoformat(),
            }
        }
        shipment.requested_pickup_date = new_date
        return _ActionOutcome(
            new_status=self._resume_status(context),
            summary=ACTION_SUMMARIES[NdrAction.RESCHEDULE_PICKUP],
            diff=diff,
        )

    async def _handle_cancel_pickup(self, context: _ActionContext) -> _ActionOutcome:
        """Cancel the pickup (prepaid freight is refunded on finalize)."""
        return _ActionOutcome(
            new_status=PickupStatus.CANCELLED,
            summary=ACTION_SUMMARIES[NdrAction.CANCEL_PICKUP],
        )


def get_exceptions_service(
    session: AsyncSession = Depends(get_session),
) -> ExceptionsService:
    """FastAPI factory wiring the repository and collaborating services on one session."""
    return ExceptionsService(
        repo=ExceptionsRepository(session),
        shipment_service=ShipmentService(ShipmentRepository(session)),
        wallet_service=WalletService(WalletRepository(session)),
    )
