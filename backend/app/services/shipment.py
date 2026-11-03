import csv
import io
import logging
import random
import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.money import ZERO_MONEY, money_to_float, to_money
from app.core.permissions import (
    assert_can_manage_shipments_or_pickups,
    assert_not_read_only,
    is_tenant_admin,
    is_tenant_staff,
)
from app.models.delhivery_modules import InvoiceNoteType, WeightDispute
from app.models.manifests import ManifestStatus, ServiceFlow
from app.models.pickups import (
    ActivityType,
    Address,
    AddressScope,
    CodRemittanceStatus,
    DocumentType,
    NdrAction,
    NdrExceptionReason,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    PickupStatus,
    ProductCategory,
    ShipmentActivity,
    ShipmentType,
)
from app.models.repricing import ChargeAdjustmentReason, MeasurementSource
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.repositories.delhivery_modules import DelhiveryModulesRepository
from app.repositories.manifests import ManifestRepository
from app.repositories.shipments import ShipmentRepository
from app.repositories.wallet import WalletRepository
from app.schemas.v1.pickups import (
    EWAY_BILL_MANDATORY_THRESHOLD,
    AppointmentUpdate,
    PickupCreate,
    PickupUpdate,
    PublicActivityRead,
    PublicTrackingRead,
    ShipmentActivityRead,
    carrier_display_name,
)
from app.services import cod_payout, ndr_rules
from app.services.delhivery_modules import (
    WEIGHT_DISPUTE_REFUND_REMARK,
    DelhiveryModulesService,
)
from app.services.notifications import notify_ndr_raised, notify_weight_debit
from app.services.pricing.booking import BookingPrice, price_booking, service_type_for
from app.services.pricing.carrier_billing import shipment_transporter_name
from app.services.public_tracking import build_public_timeline, mask_person_name
from app.services.repricing import (
    RTO_SURCHARGE_KEY,
    MeasurementInput,
    RepriceChange,
    RepriceResult,
    RepricingService,
    assert_edit_allowed,
    billing_channel_for_booking,
    edit_fields_from_update,
    is_wallet_billed,
    stamp_billing_channel,
)
from app.services.shipment_lifecycle import ShipmentLifecycleMachine
from app.services.wallet import WalletService

# --- Setup Logger ---
logger = logging.getLogger(__name__)

# Terminal statuses: no further edits or exception actions are possible (H-6, incl. RTO_DELIVERED).
TERMINAL_STATUSES = frozenset(ShipmentLifecycleMachine.TERMINAL_STATUSES)
MONEY_DECIMALS = 2
COD_VALIDATED_FIELDS = frozenset(
    {"is_cod", "cod_amount", "shipment_total_value", "add_shipping_to_cod"}
)
"""COD caps are re-validated only when one of these payment fields is edited."""
REPRICING_STATUSES = (PickupStatus.RTO_INITIATED,)
"""Status changes that alter the bill (RTO surcharge); other status clicks never re-price."""
STAFF_EDITOR_ROLES = (UserRole.admin, UserRole.owner, UserRole.operations_user)
"""Tenant staff who may edit any shipment (customers may edit only their own, plan B9)."""
CUSTOMER_FORBIDDEN_PATCH_FIELDS = frozenset(
    {
        "status",
        "ndr_reason",
        "ndr_remark",
        "charge_amount",
        "measured_weight_kg",
        "delivery_otp",
        "pod_received_by",
    }
)
"""Operations fields a customer can never set through PATCH /shipments/{id}."""
PICKUP_REJECTION_STATUSES = (PickupStatus.QC_FAILED, PickupStatus.REJECTED_AT_PICKUP)
"""Refused at the door before pickup: full refund + CN (plan B10)."""
AFTER_PICKUP_STATUSES = (
    PickupStatus.IN_TRANSIT,
    PickupStatus.OUT_FOR_DELIVERY,
    PickupStatus.RTO_INITIATED,
    PickupStatus.RTO_IN_TRANSIT,
    PickupStatus.RTO_DELIVERED,
    PickupStatus.LOST,
    PickupStatus.COMPLETED,
)
"""The parcel has left the merchant (EXCEPTION counts too unless it is a pickup-stage NPR)."""
LOST_STATUS = PickupStatus.LOST
"""Entering LOST refunds the net freight with a CN, no RTO charge (plan C4)."""
OTP_REQUIRED_STATUSES = (PickupStatus.IN_TRANSIT, PickupStatus.OUT_FOR_DELIVERY)
"""Statuses on the way to the consignee: the shipment must carry a delivery OTP (D-04b)."""
DELIVERY_OTP_MIN = 100_000
DELIVERY_OTP_SPAN = 900_000
"""6-digit OTP = DELIVERY_OTP_MIN + secrets.randbelow(DELIVERY_OTP_SPAN)."""
MISSING_OTP_DETAIL = (
    "This shipment has no delivery OTP yet, so it can't be marked Delivered. "
    "Move it to In transit or Out for delivery first."
)
ADMIN_ONLY_STATUS_DETAIL = (
    "Only the Tenant Owner or an Admin can mark a shipment Lost, mark a lost shipment found, "
    "or start a manual RTO."
)
POST_PICKUP_CANCEL_RTO_DETAIL = (
    "Once picked up, cancelling a shipment initiates a paid Return to Origin (RTO). "
    "Only the shipper, Tenant Owner, or an Admin can initiate a manual RTO."
)
EXCEPTION_EXIT_SPECIAL_STATUSES = (
    PickupStatus.RTO_INITIATED,
    PickupStatus.CANCELLED,
    PickupStatus.LOST,
)
"""Moves out of EXCEPTION governed by their own rules (A-22 role gate, post-pickup cancel -> RTO)."""
CANCEL_TO_RTO_COMMENT = "Cancelled after pickup: converted to Return to Origin (RTO)."
"""Activity text when a post-pickup cancel becomes an RTO (plan B10, DO1 cancel-forward-order)."""
PICKUP_MEASUREMENT_REMARK_TEMPLATE = "Charged weight {old} kg → {new} kg ({boxes} boxes) at pickup"
"""Merchant wallet remark for a rider's Actual pieces (plan B5)."""
HUB_MEASUREMENT_REMARK_TEMPLATE = "Charged weight {old} kg → {new} kg at hub"
"""Merchant wallet remark for a hub measurement."""
GRAMS_PER_KG = 1000.0
PAYMENT_COMPLIANCE_FIELDS = frozenset(
    {
        "currency",
        "hsn_code",
        "invoice_numbers",
        "invoice_date",
        "eway_bill_numbers",
        "shipment_value",
        "shipment_tax_value",
    }
)
"""Payment fields a PATCH may copy directly; every price input goes through RepricingService."""
RTO_FREIGHT_REMARK_TEMPLATE = "RTO freight deducted for {tracking_id}"
"""Ledger remark for the RTO surcharge debit (merchant RTO, auto-RTO and admin RTO)."""


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (TIMESTAMP WITHOUT TIME ZONE columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ShipmentService:
    """
    Handles business logic for Shipments.
    Orchestrates the creation of addresses, packages, and the shipment record.
    """

    def __init__(self, shipment_repo: ShipmentRepository):
        self.shipment_repo = shipment_repo

    # --- Read & Tracking Logic ---

    async def get_shipment_details(
        self, shipment_id: uuid.UUID, user: User, tenant_id: uuid.UUID
    ) -> PickupRequest:
        """
        Get Full Details of a single shipment.
        - **Admin/Owner**: Can see ANY shipment in the tenant.
        - **Customer**: Can ONLY see their own shipment.
        """
        # 1. Fetch data (eagerly loaded)
        shipment = await self.shipment_repo.get_shipment_full_details(
            shipment_id, tenant_id
        )

        # 2. Basic Existence Check
        if not shipment or shipment.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        # 3. Ownership Check (The Guard Rail)
        # If user is NOT tenant staff, they MUST be the creator of this shipment.
        if not is_tenant_staff(user):
            if shipment.created_by_user_id != user.id:
                # We return 404 instead of 403 to prevent ID enumeration scanning
                raise HTTPException(status_code=404, detail="Shipment not found")

        # 4. Fetch the creator's email and attach it as a dynamic attribute
        creator = await self.shipment_repo.session.get(
            User, shipment.created_by_user_id
        )
        if creator:
            object.__setattr__(shipment, "creator_email", creator.email)
        self._attach_staff_transporter(shipment, user)

        return shipment

    @staticmethod
    def _attach_staff_transporter(shipment: PickupRequest, user: Optional[User]) -> None:
        """Attaches the Prime transporter name for tenant staff only (never customers)."""
        value = shipment_transporter_name(shipment) if is_tenant_staff(user) else None
        object.__setattr__(shipment, "transporter_name", value)

    async def get_timeline(
        self, shipment_id: uuid.UUID, user: User, tenant_id: uuid.UUID
    ) -> List[ShipmentActivityRead]:
        """
        Get Audit Timeline.
        Tenant staff see everything. Customers see only public events for their own shipments.
        """
        # 1. Verify Shipment belongs to tenant
        shipment = await self.shipment_repo.get_shipment_full_details(
            shipment_id, tenant_id
        )
        if not shipment or shipment.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        is_admin = is_tenant_staff(user)

        # 2. Security Check for Customers (Must own the shipment)
        if not is_admin:
            if shipment.created_by_user_id != user.id:
                raise HTTPException(status_code=404, detail="Shipment not found")

        # 3. Fetch History
        activities = await self.shipment_repo.get_shipment_history(
            shipment_id, tenant_id
        )

        # 4. Map to Schema & Filter
        result = []
        for a in activities:
            if not is_admin and not a.is_public:
                # Allow the customer to see the initial creation event so the timeline isn't empty
                if a.summary != "Shipment Created":
                    continue

            result.append(
                ShipmentActivityRead(
                    id=a.id,
                    timestamp=a.timestamp,
                    user_id=a.user_id,
                    activity_type=a.activity_type,
                    summary=a.summary,
                    comment=a.comment,
                    is_public=a.is_public,
                    diff=a.diff,
                )
            )

        return result

    async def track_shipment_public(
        self, identifier: str, tenant_id: uuid.UUID
    ) -> PublicTrackingRead:
        """
        Public Access: Get sanitized shipment status.
        Does NOT require login, BUT requires the correct Tenant context.
        Accepts either a Tracking ID (NAV-XXXX) or an internal Shipment UUID.
        """
        try:
            # Try parsing as UUID first
            shipment_uuid = uuid.UUID(identifier)
            shipment = await self.shipment_repo.get_shipment_full_details(
                shipment_uuid, tenant_id
            )
        except ValueError:
            # Fallback to Tracking ID
            shipment = await self.shipment_repo.get_shipment_by_tracking_id(
                identifier, tenant_id
            )

        # 🔥 THE SECURITY FIX: Must exist AND belong to the requested tenant!
        if not shipment or shipment.tenant_id != tenant_id:
            logger.warning(
                f"Tracking lookup failed or blocked for identifier: {identifier}"
            )
            raise HTTPException(status_code=404, detail="Shipment not found")

        # Fetch activities to build the public timeline
        activities = await self.shipment_repo.get_shipment_history(
            shipment.id, tenant_id
        )

        # B-03: only allow-listed milestones with fixed wording; never free text, money,
        # weights, NDR codes or package contents (anyone with the link can see this page).
        public_timeline = [
            PublicActivityRead(
                timestamp=event.timestamp, status_title=event.title, message=event.message
            )
            for event in build_public_timeline(activities)
        ]

        return PublicTrackingRead(
            tracking_id=shipment.tracking_id,  # type: ignore
            status=shipment.status,
            current_location="Processing",
            estimated_delivery=None,
            carrier_name=carrier_display_name(shipment.service_option),
            carrier_awb=shipment.carrier_awb,
            delivery_otp=None,
            pod_received_by=mask_person_name(shipment.pod_received_by),
            timeline=public_timeline,
            package_details=[],
        )

    async def list_my_shipments(
        self,
        user: User,
        tenant_id: uuid.UUID,
        page: int,
        size: int,
        is_b2b: Optional[bool] = None,
        statuses: Optional[List[PickupStatus]] = None,
        shipment_type: Optional[ShipmentType] = None,
    ) -> Tuple[List[PickupRequest], int]:
        """
        Smart Listing:
        - Tenant staff see ALL shipments for the tenant.
        - Customers see ONLY their own shipments.
        - `statuses` and `shipment_type` optionally narrow results server-side.
        """
        items, total = await self.shipment_repo.list_shipments(
            tenant_id=tenant_id,
            user_id=None if is_tenant_staff(user) else user.id,
            page=page,
            size=size,
            is_b2b=is_b2b,
            statuses=statuses,
            shipment_type=shipment_type,
        )
        for item in items:
            self._attach_staff_transporter(item, user)
        return items, total

    @staticmethod
    def _assert_eway_bill_on_booking(payload: PickupCreate) -> None:
        """
        E-way bill rule for goods ≥ ₹50,000 (the declared total is server-computed, D-06):
        a 12-digit e-way bill number or an uploaded EWAY_BILL document is required.

        Raises:
            HTTPException(400): missing or malformed e-way bill.
        """
        payment = payload.payment_details
        if not payment.shipment_total_value or payment.shipment_total_value < EWAY_BILL_MANDATORY_THRESHOLD:
            return
        numbers = [eb for eb in (payment.eway_bill_numbers or []) if eb.strip()]
        has_document = any(doc.document_type == DocumentType.EWAY_BILL for doc in payload.documents)
        if not (numbers or has_document):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"E-Way bill is mandatory for shipments with value >= {EWAY_BILL_MANDATORY_THRESHOLD} INR. Provide either eway_bill_numbers or upload an EWAY_BILL document.",
            )
        for eway in numbers:
            if not re.match(r"^\d{12}$", eway.strip()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid E-Way bill format: '{eway}'. Must be exactly 12 digits.",
                )

    @staticmethod
    def _booking_payment_model(
        payload: PickupCreate, booking_price: BookingPrice, *, booked_by_staff: bool
    ) -> PaymentDetails:
        """
        The payment row of a new booking. Every price column comes from the server price
        (client pricing values are ignored); the goods COD is what the seller typed (A-01)
        and the door amount comes from `cod_payout` only.

        Args:
            payload: The booking body.
            booking_price: The fresh server price (D3).
            booked_by_staff: Staff POSTPAID bookings are not wallet-billed (B16).

        Returns:
            An unsaved PaymentDetails.
        """
        payment = payload.payment_details
        priced = booking_price.priced
        is_cod = payment.is_cod
        cod_amount, freight_collectible = cod_payout.collectible_amounts(
            is_cod=is_cod,
            goods=to_money(payment.cod_amount) if is_cod else ZERO_MONEY,
            total=priced.sell.total,
            mode=payment.freight_payment_mode,
            add_shipping_to_cod=payment.add_shipping_to_cod,
            merchant_paid=ZERO_MONEY,
        )
        channel = billing_channel_for_booking(payment.freight_payment_mode, booked_by_staff=booked_by_staff)
        return PaymentDetails(
            currency=payment.currency,
            freight_payment_mode=payment.freight_payment_mode,
            is_cod=is_cod,
            cod_amount=money_to_float(cod_amount),
            freight_collectible=freight_collectible,
            add_shipping_to_cod=payment.add_shipping_to_cod and is_cod,
            shipment_value=payment.shipment_value,
            shipment_tax_value=payment.shipment_tax_value,
            shipment_total_value=payment.shipment_total_value,
            hsn_code=payment.hsn_code,
            invoice_numbers=payment.invoice_numbers,
            invoice_date=payment.invoice_date,
            eway_bill_numbers=payment.eway_bill_numbers,
            base_freight=money_to_float(priced.sell.forward_freight),
            tax_amount=money_to_float(priced.sell.gst),
            total_logistics_cost=money_to_float(priced.sell.total),
            pricing_breakdown=stamp_billing_channel(priced.breakdown, channel),
            chargeable_weight=float(priced.chargeable_weight_kg),
            carrier_cost=booking_price.carrier_cost,
        )

    async def _generate_unique_tracking_id(self, tenant_slug: str) -> str:
        """
        Generates a unique tracking ID (e.g., NAVIERA-X9A2B3C4).
        Checks the database to ensure no collisions exist.
        Retries automatically if a collision is found.
        """
        prefix = tenant_slug.upper()

        # Loop until a unique ID is found (usually runs once)
        while True:
            # Generate 8-char suffix: X9A2B3C4
            chars = string.ascii_uppercase + string.digits
            suffix = "".join(random.choices(chars, k=8))
            candidate_id = f"{prefix}-{suffix}"

            # Check DB for existence
            is_taken = await self.shipment_repo.check_tracking_id_exists(candidate_id)

            if not is_taken:
                return candidate_id

            logger.warning(
                f"Collision detected for Tracking ID {candidate_id}. Retrying..."
            )

    async def create_shipment(
        self,
        *,
        payload: PickupCreate,
        tenant: Tenant,
        user_id: uuid.UUID,
        actor: Optional[User] = None,
    ) -> PickupRequest:
        """
        Main entry point for creating a shipment.
        Handles the complexity of "Saved Address" vs "New Address".
        `actor` (the authenticated user) enables the customer service-scope check.
        The price is always computed fresh on the server (DESIGN.md v4 D3, `pricing/booking.py`).
        """
        logger.info("Service: Starting shipment creation logic")
        assert_can_manage_shipments_or_pickups(actor, "create shipments")

        if (
            payload.shipment_type == ShipmentType.REVERSE
            and not payload.reason_for_return
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reason_for_return is required for REVERSE shipments",
            )

        # --- 1. Resolve Pickup Address ---
        new_pickup_addr_model: Optional[Address] = None
        final_pickup_id: uuid.UUID
        pickup_pincode = ""

        if payload.pickup_address_id:
            # Case A: User selected a Saved Address
            logger.debug(
                f"Resolving Saved Pickup Address ID: {payload.pickup_address_id}"
            )
            existing_addr = await self.shipment_repo.get_address_by_id(
                payload.pickup_address_id, tenant.id
            )

            # SECURITY CHECK: Ensure address belongs to this tenant and is accessible to caller
            is_customer_actor = (
                actor is not None and actor.role == UserRole.customer
            )
            if (
                not existing_addr
                or existing_addr.tenant_id != tenant.id
                or (
                    is_customer_actor
                    and existing_addr.user_id != user_id
                    and existing_addr.scope != AddressScope.TENANT
                )
            ):
                logger.warning(
                    f"Security Alert: User tried to access invalid/other tenant address: {payload.pickup_address_id}"
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Pickup Address not found or access denied",
                )
            final_pickup_id = existing_addr.id
            pickup_pincode = existing_addr.pincode
        elif payload.new_pickup_address:
            # Case B: User provided a New Address Object
            logger.debug("Processing New Pickup Address Snapshot")
            final_pickup_id = uuid.uuid4()
            pickup_dump = payload.new_pickup_address.model_dump()
            if actor is not None and actor.role == UserRole.customer:
                pickup_dump["scope"] = AddressScope.PRIVATE
            new_pickup_addr_model = Address(
                id=final_pickup_id,
                **pickup_dump,
                tenant_id=tenant.id,
                user_id=user_id,
            )
            pickup_pincode = payload.new_pickup_address.pincode
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pickup Address is required",
            )

        # --- 2. Resolve Delivery Address ---
        new_delivery_addr_model: Optional[Address] = None
        final_delivery_id: uuid.UUID
        delivery_pincode = ""

        if payload.delivery_address_id:
            logger.debug(
                f"Resolving Saved Delivery Address ID: {payload.delivery_address_id}"
            )
            existing_del = await self.shipment_repo.get_address_by_id(
                payload.delivery_address_id, tenant.id
            )
            is_customer_actor = (
                actor is not None and actor.role == UserRole.customer
            )
            if (
                not existing_del
                or existing_del.tenant_id != tenant.id
                or (
                    is_customer_actor
                    and existing_del.user_id != user_id
                    and existing_del.scope != AddressScope.TENANT
                )
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Delivery Address not found or access denied",
                )
            final_delivery_id = existing_del.id
            delivery_pincode = existing_del.pincode
        elif payload.new_delivery_address:
            logger.debug("Processing New Delivery Address Snapshot")
            final_delivery_id = uuid.uuid4()
            delivery_dump = payload.new_delivery_address.model_dump()
            if actor is not None and actor.role == UserRole.customer:
                delivery_dump["scope"] = AddressScope.PRIVATE
            new_delivery_addr_model = Address(
                id=final_delivery_id,
                **delivery_dump,
                tenant_id=tenant.id,
                user_id=user_id,
            )
            delivery_pincode = payload.new_delivery_address.pincode
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Delivery Address is required",
            )

        # --- 3. B2B Operational Rules Validation (Stateful) ---
        if payload.is_blind_pickup:
            if payload.packages:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Packages cannot be provided for blind pickups.",
                )
            if not payload.estimated_box_count or payload.estimated_box_count <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Estimated box count must be greater than 0 for blind pickups.",
                )
        else:
            if not payload.packages or len(payload.packages) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Package details are mandatory for manifested (non-blind) pickups.",
                )

        if payload.is_carriers_risk:
            if (
                not payload.payment_details
                or payload.payment_details.shipment_total_value <= 0
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Shipment total value must be greater than 0 when carrier's risk is enabled.",
                )

        # --- 4. Prepare Child Objects & Price the booking (DESIGN.md v4 D3) ---
        package_models = [
            PackageDetails(**pkg.model_dump()) for pkg in payload.packages
        ]
        document_models = [
            PickupDocument(**doc.model_dump()) for doc in payload.documents
        ]

        booking_price = await price_booking(
            self.shipment_repo.session,
            tenant,
            payload,
            pickup_pincode=pickup_pincode,
            delivery_pincode=delivery_pincode,
        )
        is_b2b_order = booking_price.flow == ServiceFlow.B2B
        self._assert_service_scope(actor, is_b2b_order)
        self._assert_eway_bill_on_booking(payload)
        payment_model = self._booking_payment_model(
            payload, booking_price, booked_by_staff=actor is None or is_tenant_staff(actor)
        )

        # --- 5. Prepare Shipment Header ---
        if payload.ndr_reason is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set ndr_reason during shipment creation",
            )

        new_tracking_id = await self._generate_unique_tracking_id(tenant.slug)

        final_other_desc = (
            payload.other_category_description
            if payload.product_category == ProductCategory.OTHER
            else None
        )

        pickup_request = PickupRequest(
            tenant_id=tenant.id,
            created_by_user_id=user_id,
            order_reference_id=payload.order_reference_id,
            tracking_id=new_tracking_id,
            shipment_type=payload.shipment_type,
            service_type=service_type_for(booking_price.option),
            service_option=booking_price.option,
            requested_pickup_date=payload.requested_pickup_date,
            pickup_time_slot=payload.pickup_time_slot,
            po_number=payload.po_number,
            po_date=payload.po_date,
            po_expiry_date=payload.po_expiry_date,
            appointment_id=payload.appointment_id,
            appointment_start=payload.appointment_start,
            appointment_end=payload.appointment_end,
            pickup_strategy=payload.pickup_strategy,
            product_category=payload.product_category,
            other_category_description=final_other_desc,
            is_blind_pickup=payload.is_blind_pickup,
            estimated_box_count=payload.estimated_box_count,
            is_carriers_risk=payload.is_carriers_risk,
            reason_for_return=payload.reason_for_return,
            qc_required=payload.qc_required,
            qc_notes=payload.qc_notes,
            status=PickupStatus.OPEN,  # Ready to Ship once booked (Delhivery parity)
            pickup_address_id=final_pickup_id,
            delivery_address_id=final_delivery_id,
        )

        initial_activity = ShipmentActivity(
            pickup_id=pickup_request.id,
            user_id=user_id,
            activity_type=ActivityType.INFO_UPDATE,
            summary="Shipment Created",
            comment="Initial Creation",
            is_public=True,
            diff={},
        )

        logger.info("Service: Delegating to Repository for Atomic Transaction")
        created_shipment = await self.shipment_repo.create_shipment_transactional(
            pickup=pickup_request,
            packages=package_models,
            documents=document_models,
            payment=payment_model,
            new_pickup_address=new_pickup_addr_model,
            new_delivery_address=new_delivery_addr_model,
            activity=initial_activity,
        )

        # Wallet-billed bookings (PREPAID, or POSTPAID booked by a customer, B16) debit the
        # creator's wallet and get their GST INVOICE; TO_PAY and staff POSTPAID do not.
        if (
            created_shipment.payment_details
            and is_wallet_billed(created_shipment.payment_details)
            and created_shipment.payment_details.total_logistics_cost > 0
        ):
            wallet_service = WalletService(
                WalletRepository(self.shipment_repo.session)
            )
            await wallet_service.deduct_shipment_spend(
                user_id=user_id,
                tenant=tenant,
                shipment=created_shipment,
                amount=created_shipment.payment_details.total_logistics_cost,
                is_b2b=is_b2b_order,
            )
            delhivery_service = DelhiveryModulesService(
                DelhiveryModulesRepository(self.shipment_repo.session)
            )
            await delhivery_service.record_shipment_billing_note(
                shipment=created_shipment,
                note_type=InvoiceNoteType.INVOICE.value,
                is_b2b=is_b2b_order,
            )

        await self.shipment_repo.session.commit()
        return created_shipment

    # --- 2. The Diff Engine (Helper) ---

    def _calculate_diff(
        self, old_obj: PickupRequest, update_data: PickupUpdate
    ) -> Dict:
        """
        Compares the Old Shipment vs. The Update Payload.
        Returns a dictionary of changes (The 'Diff').
        """
        diff = {}

        # A. Simple Fields
        fields_to_check = [
            "status",
            "service_type",
            "service_option",
            "requested_pickup_date",
            "pickup_time_slot",
            "order_reference_id",
            "product_category",
            "other_category_description",
            "reason_for_return",
            "ndr_reason",
            # --- NEW: B2B Fields ---
            "po_number",
            "po_date",
            "po_expiry_date",
            "appointment_id",
            "appointment_start",
            "appointment_end",
            "pickup_strategy",
            # Operational B2B Flags
            "is_blind_pickup",
            "estimated_box_count",
            "is_carriers_risk",
        ]

        update_dict = update_data.model_dump(exclude_unset=True)

        for field in fields_to_check:
            if field in update_dict:
                new_val = getattr(update_data, field)
                old_val = getattr(old_obj, field)

                # Helper to handle Date comparison vs String comparison
                if new_val != old_val:
                    # Convert dates to ISO string for JSON serialization
                    old_json = (
                        old_val.isoformat()
                        if hasattr(old_val, "isoformat")
                        else old_val
                    )
                    new_json = (
                        new_val.isoformat()
                        if hasattr(new_val, "isoformat")
                        else new_val
                    )

                    diff[field] = {"old": old_json, "new": new_json}

        # B. Packages (List Sync Logic)
        if update_data.packages is not None:
            pkg_diff = {"modified": [], "added": [], "removed": []}

            # Map existing DB packages by ID
            old_pkgs_map = {p.id: p for p in old_obj.packages}

            # IDs present in the payload
            payload_ids = set()

            for pkg_in in update_data.packages:
                if pkg_in.id and pkg_in.id in old_pkgs_map:
                    # Case 1: Update existing
                    payload_ids.add(pkg_in.id)
                    old_pkg = old_pkgs_map[pkg_in.id]

                    # Check internal changes
                    changes = {}
                    fields_to_check = [
                        k
                        for k in [
                            "weight",
                            "length",
                            "breadth",
                            "height",
                            "description",
                            "box_count",
                            "is_fragile",
                            "dimension_unit",
                            "weight_unit",
                        ]
                        if k in pkg_in.model_fields_set
                    ]
                    for k in fields_to_check:
                        val_new = getattr(pkg_in, k)
                        val_old = getattr(old_pkg, k)
                        if val_new != val_old:
                            changes[k] = {"old": val_old, "new": val_new}

                    if changes:
                        pkg_diff["modified"].append(
                            {"id": str(pkg_in.id), "changes": changes}
                        )
                else:
                    # Case 2: Add new
                    pkg_diff["added"].append(pkg_in.model_dump(exclude={"id"}))

            # Case 3: Remove (In DB but not in Payload)
            for old_id, old_pkg in old_pkgs_map.items():
                if old_id not in payload_ids:
                    pkg_diff["removed"].append(
                        {"id": str(old_id), "desc": old_pkg.description}
                    )

            if any(pkg_diff.values()):
                diff["packages"] = pkg_diff

        # C. Documents (List Sync Logic)
        if update_data.documents is not None:
            doc_diff = {"added": [], "removed": []}
            old_docs_map = {d.id: d for d in old_obj.documents}
            payload_ids = set()

            for doc_in in update_data.documents:
                if doc_in.id and doc_in.id in old_docs_map:
                    payload_ids.add(doc_in.id)
                else:
                    doc_diff["added"].append(doc_in.file_name)

            for old_id, old_doc in old_docs_map.items():
                if old_id not in payload_ids:
                    doc_diff["removed"].append(old_doc.file_name)

            if any(doc_diff.values()):
                diff["documents"] = doc_diff

        return diff

    @staticmethod
    def _validate_status_transition(current_status: PickupStatus, new_status: PickupStatus) -> None:
        """
        Enforces the Phase C lifecycle (plan C1, H-6) through the single state machine:
        nothing leaves a terminal status, no RTO status becomes COMPLETED, and QC_FAILED /
        REJECTED_AT_PICKUP are reachable only before pickup.

        Raises:
            HTTPException(400): The move is not allowed.
        """
        ShipmentLifecycleMachine.validate_transition(current_status, new_status)

    # --- 3. Update Flow (The Main Logic) ---

    async def update_shipment(
        self,
        shipment_id: uuid.UUID,
        payload: PickupUpdate,
        user: User,
        tenant_id: uuid.UUID,
    ) -> PickupRequest:
        # 1. Permission Check (staff edit any shipment; customers only their own, B9)
        assert_can_manage_shipments_or_pickups(user, "modify shipments")
        assert_not_read_only(user, "modify shipments")
        is_customer = user.role == UserRole.customer
        if not is_customer and user.role not in STAFF_EDITOR_ROLES:
            raise HTTPException(
                status_code=403, detail="Only Admins can edit shipments"
            )

        # 2. Fetch Current State, row-locked so an edit never races a re-price or RTO
        reprice = RepricingService(self.shipment_repo.session)
        await reprice.load_shipment(shipment_id, tenant_id, for_update=True)
        current = await self.shipment_repo.get_shipment_full_details(
            shipment_id, tenant_id
        )
        if not current or current.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")
        if is_customer and current.created_by_user_id != user.id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        if current.status in TERMINAL_STATUSES:
            raise HTTPException(
                status_code=400, detail="Cannot modify a shipment in a terminal state."
            )
        if is_customer:
            self._assert_customer_patch_scope(payload)
        assert_edit_allowed(current, edit_fields_from_update(payload, current), user)
        held_from = (
            await self.shipment_repo.get_held_from_status(shipment_id, tenant_id)
            if current.status == PickupStatus.EXCEPTION
            else None
        )
        payload, cancel_converted = self._convert_post_pickup_cancel(current, payload, held_from)
        replayed = await self._replay_or_reject_duplicate_raise(current, payload)
        if replayed is not None:
            return replayed

        original_ndr_reason = current.ndr_reason
        original_status = current.status
        update_dict = payload.model_dump(exclude_unset=True)

        for field in ["status", "product_category", "requested_pickup_date"]:
            if field in update_dict and update_dict[field] is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{field} cannot be null",
                )

        if current.shipment_type == ShipmentType.REVERSE:
            resolved_reason = (
                payload.reason_for_return
                if "reason_for_return" in update_dict
                else current.reason_for_return
            )
            if not resolved_reason:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="reason_for_return is required for REVERSE shipments",
                )

        # Validate other category description
        resolved_category = (
            payload.product_category
            if payload.product_category is not None
            else current.product_category
        )
        resolved_description = (
            payload.other_category_description
            if "other_category_description" in update_dict
            else current.other_category_description
        )
        if resolved_category == ProductCategory.OTHER and not resolved_description:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="other_category_description is required when product_category is OTHER",
            )

        # --- 3. B2B Operational Rules Validation (Stateful) ---
        if (
            payload.is_blind_pickup is not None
            and payload.is_blind_pickup != current.is_blind_pickup
        ):
            if current.status not in [PickupStatus.DRAFT, PickupStatus.OPEN]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot toggle blind pickup status after the shipment is assigned or manifested.",
                )

        resolved_is_blind = (
            payload.is_blind_pickup
            if payload.is_blind_pickup is not None
            else current.is_blind_pickup
        )
        resolved_box_count = (
            payload.estimated_box_count
            if payload.estimated_box_count is not None
            else current.estimated_box_count
        )

        if resolved_is_blind:
            if payload.packages:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Packages cannot be provided for blind pickups.",
                )
            if not resolved_box_count or resolved_box_count <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Estimated box count must be greater than 0 for blind pickups.",
                )
        else:
            resolved_packages = (
                payload.packages if payload.packages is not None else current.packages
            )
            if not resolved_packages or len(resolved_packages) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Package details are mandatory for manifested (non-blind) pickups.",
                )

        resolved_is_carriers_risk = (
            payload.is_carriers_risk
            if payload.is_carriers_risk is not None
            else current.is_carriers_risk
        )
        resolved_total_value = 0.0
        if (
            payload.payment_details
            and "shipment_total_value" in payload.payment_details.model_fields_set
        ):
            resolved_total_value = payload.payment_details.shipment_total_value
        elif current.payment_details:
            resolved_total_value = current.payment_details.shipment_total_value

        if resolved_is_carriers_risk and resolved_total_value <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shipment total value must be greater than 0 when carrier's risk is enabled.",
            )

        resolved_is_cod = (
            payload.payment_details.is_cod
            if (
                payload.payment_details
                and "is_cod" in payload.payment_details.model_fields_set
            )
            else (current.payment_details.is_cod if current.payment_details else False)
        )
        resolved_cod_amount = (
            payload.payment_details.cod_amount
            if (
                payload.payment_details
                and "cod_amount" in payload.payment_details.model_fields_set
            )
            else (
                current.payment_details.cod_amount if current.payment_details else 0.0
            )
        )

        cod_fields_in_payload = bool(
            payload.payment_details
            and COD_VALIDATED_FIELDS & payload.payment_details.model_fields_set
        )
        if resolved_is_cod and cod_fields_in_payload:
            self._validate_cod_amount(
                current, payload, resolved_cod_amount, resolved_total_value
            )

        # 4. Calculate Diff
        diff = self._calculate_diff(current, payload)

        if payload.status:
            self._validate_status_transition(current.status, payload.status)
            self._assert_status_change_role(user, payload.status, current.status, cancel_converted)
            if current.status == PickupStatus.EXCEPTION and payload.status != PickupStatus.EXCEPTION:
                self._assert_exception_exit(current, payload.status, held_from)
            if payload.status == PickupStatus.COMPLETED and not current.delivery_otp:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=MISSING_OTP_DETAIL
                )
            if (
                payload.status == PickupStatus.COMPLETED
                and current.delivery_otp
                and payload.delivery_otp != current.delivery_otp
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid 6-digit Delivery OTP. Please enter the valid consignee OTP to mark this shipment as COMPLETED.",
                )
            if (
                payload.status == PickupStatus.COMPLETED
                and payload.expected_cod_amount is not None
            ):
                actual_cod = (
                    float(current.payment_details.cod_amount or 0.0)
                    if (current.payment_details and current.payment_details.is_cod)
                    else 0.0
                )
                if abs(float(payload.expected_cod_amount) - actual_cod) > 0.01:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"COD collectible changed on the server (now ₹{actual_cod:.2f}). "
                            "Refresh the screen and collect the updated amount before marking Delivered."
                        ),
                    )

        # Validate NDR Reason
        resolved_status = payload.status if payload.status else current.status
        resolved_ndr = (
            payload.ndr_reason if "ndr_reason" in update_dict else current.ndr_reason
        )
        if resolved_status == PickupStatus.EXCEPTION and not resolved_ndr:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ndr_reason is required when status is EXCEPTION",
            )
        is_raising_exception = payload.status == PickupStatus.EXCEPTION
        if is_raising_exception:
            self._validate_exception_raise(resolved_ndr, payload)
            stage_error = ndr_rules.raise_rejection(
                resolved_ndr, current.shipment_type, original_status
            )
            if stage_error:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=stage_error)

        # 4b. Work out the re-price BEFORE the header changes (compares against stored values)
        price_change = await reprice.change_from_update(current, payload, tenant_id, user)

        # 5. Handle Address Snapshots
        new_pickup_addr = None
        if payload.new_pickup_address:
            new_pickup_addr = Address(
                id=uuid.uuid4(),
                **payload.new_pickup_address.model_dump(),
                tenant_id=tenant_id,
                user_id=user.id,
            )
            diff["pickup_address"] = "Updated Address Details (Snapshot)"
        elif (
            payload.pickup_address_id
            and payload.pickup_address_id != current.pickup_address_id
        ):
            addr = await self.shipment_repo.get_address_by_id(
                payload.pickup_address_id, tenant_id
            )
            if not addr or addr.tenant_id != tenant_id:
                raise HTTPException(404, "Invalid Pickup Address ID")
            current.pickup_address_id = payload.pickup_address_id
            diff["pickup_address"] = (
                f"Changed to Address ID {payload.pickup_address_id}"
            )

        new_delivery_addr = None
        if payload.new_delivery_address:
            new_delivery_addr = Address(
                id=uuid.uuid4(),
                **payload.new_delivery_address.model_dump(),
                tenant_id=tenant_id,
                user_id=user.id,
            )
            diff["delivery_address"] = "Updated Address Details (Snapshot)"
        elif (
            payload.delivery_address_id
            and payload.delivery_address_id != current.delivery_address_id
        ):
            addr = await self.shipment_repo.get_address_by_id(
                payload.delivery_address_id, tenant_id
            )
            if not addr or addr.tenant_id != tenant_id:
                raise HTTPException(404, "Invalid Delivery Address ID")
            current.delivery_address_id = payload.delivery_address_id
            diff["delivery_address"] = (
                f"Changed to Address ID {payload.delivery_address_id}"
            )

        # 6. Prepare Lists for Sync (Packages)
        packages_to_add = []
        packages_to_delete = []
        if resolved_is_blind:
            # Under blind pickups, delete all existing packages
            if current.packages:
                packages_to_delete.extend(current.packages)
                current.packages = []
        else:
            if payload.packages is not None:
                old_pkgs_map = {p.id: p for p in current.packages}
                payload_ids = set()

                for pkg_in in payload.packages:
                    if pkg_in.id and pkg_in.id in old_pkgs_map:
                        payload_ids.add(pkg_in.id)
                        existing = old_pkgs_map[pkg_in.id]
                        for k, v in pkg_in.model_dump(
                            exclude={"id"}, exclude_unset=True
                        ).items():
                            setattr(existing, k, v)
                    else:
                        packages_to_add.append(
                            PackageDetails(**pkg_in.model_dump(exclude={"id"}))
                        )

                for old_id, old_pkg in old_pkgs_map.items():
                    if old_id not in payload_ids:
                        packages_to_delete.append(old_pkg)

        # 7. Prepare Lists for Sync (Documents)
        documents_to_add = []
        documents_to_delete = []
        if payload.documents is not None:
            old_docs_map = {d.id: d for d in current.documents}
            payload_ids = set()
            for doc_in in payload.documents:
                if doc_in.id and doc_in.id in old_docs_map:
                    payload_ids.add(doc_in.id)
                    existing = old_docs_map[doc_in.id]
                    for k, v in doc_in.model_dump(
                        exclude={"id"}, exclude_unset=True
                    ).items():
                        setattr(existing, k, v)
                else:
                    documents_to_add.append(
                        PickupDocument(**doc_in.model_dump(exclude={"id"}))
                    )
            for old_id, old_doc in old_docs_map.items():
                if old_id not in payload_ids:
                    documents_to_delete.append(old_doc)

        # 8. Apply Simple Updates to Header
        if "status" in update_dict:
            current.status = payload.status
        is_cancelling = (
            payload.status == PickupStatus.CANCELLED
            and original_status != PickupStatus.CANCELLED
        )
        is_pickup_rejected = (
            payload.status in (PickupStatus.QC_FAILED, PickupStatus.REJECTED_AT_PICKUP)
            and original_status != payload.status
        )
        is_entering_lost = payload.status == LOST_STATUS and original_status != LOST_STATUS
        detached_manifest_id = current.manifest_id if (is_cancelling or is_pickup_rejected) else None
        if is_cancelling or is_pickup_rejected:
            diff.update(self.release_for_cancellation(current))
            await self._sync_manifest_after_detach(detached_manifest_id, current.id, tenant_id)
        if "requested_pickup_date" in update_dict:
            current.requested_pickup_date = payload.requested_pickup_date
        if "pickup_time_slot" in update_dict:
            current.pickup_time_slot = payload.pickup_time_slot

        if payload.comment and payload.status:
            current.latest_status_comment = payload.comment

        if "order_reference_id" in update_dict:
            current.order_reference_id = payload.order_reference_id
        if "product_category" in update_dict:
            current.product_category = payload.product_category

        if current.product_category != ProductCategory.OTHER:
            diff.pop("other_category_description", None)
            if current.other_category_description is not None:
                diff["other_category_description"] = {
                    "old": current.other_category_description,
                    "new": None,
                }
            current.other_category_description = None
        elif "other_category_description" in update_dict:
            current.other_category_description = payload.other_category_description

        if "reason_for_return" in update_dict:
            current.reason_for_return = payload.reason_for_return

        if "qc_required" in update_dict:
            current.qc_required = payload.qc_required

        if "qc_notes" in update_dict:
            current.qc_notes = payload.qc_notes

        if "po_number" in update_dict:
            current.po_number = payload.po_number
        if "po_date" in update_dict:
            current.po_date = payload.po_date
        if "po_expiry_date" in update_dict:
            current.po_expiry_date = payload.po_expiry_date
        if "appointment_id" in update_dict:
            current.appointment_id = payload.appointment_id
        if "appointment_start" in update_dict:
            current.appointment_start = payload.appointment_start
        if "appointment_end" in update_dict:
            current.appointment_end = payload.appointment_end
        if "pickup_strategy" in update_dict:
            current.pickup_strategy = payload.pickup_strategy

        if "is_blind_pickup" in update_dict:
            current.is_blind_pickup = payload.is_blind_pickup
        if "estimated_box_count" in update_dict:
            current.estimated_box_count = payload.estimated_box_count
        if "is_carriers_risk" in update_dict:
            current.is_carriers_risk = payload.is_carriers_risk

        if "ndr_reason" in update_dict:
            current.ndr_reason = payload.ndr_reason

        if current.status != PickupStatus.EXCEPTION and current.ndr_reason is not None:
            diff.pop("ndr_reason", None)
            if original_ndr_reason is not None:
                diff["ndr_reason"] = {"old": original_ndr_reason, "new": None}
            current.ndr_reason = None

        if is_raising_exception:
            diff["ndr_raise"] = self._record_exception_raise(current, payload)
            diff["ndr_raise"]["held_from"] = original_status.value
        elif current.status != PickupStatus.EXCEPTION:
            self._clear_exception_tracking(current)

        # --- 8b. 6-Digit Delivery OTP Generation & Verification ---
        if payload.status in OTP_REQUIRED_STATUSES:
            diff.update(self.ensure_delivery_otp(current))

        if payload.status == PickupStatus.COMPLETED:
            if current.delivery_otp and payload.delivery_otp != current.delivery_otp:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid 6-digit Delivery OTP. Please enter the valid consignee OTP to mark this shipment as COMPLETED.",
                )
            current.pod_received_by = (
                (payload.pod_received_by or "").strip() or "Consignee"
            )
            diff["pod_received_by"] = {"old": None, "new": current.pod_received_by}

        # --- 9. Re-price through the single writer (plan B1/B3) ---
        # Only a real change of a price input re-prices; pure status / comment / POD / NDR
        # updates never touch freight or the wallet. A move to RTO_INITIATED is billed after
        # the save by `apply_rto_charges` (shared with merchant RTO and auto-RTO).
        is_entering_rto = (
            payload.status in REPRICING_STATUSES and payload.status != original_status
        )
        if payload.payment_details is not None and current.payment_details is not None:
            self._apply_payment_compliance_fields(current.payment_details, payload)
        tenant_obj = await self.shipment_repo.session.get(Tenant, tenant_id)
        is_leaving_lost = original_status == LOST_STATUS and payload.status not in (None, LOST_STATUS)
        if is_leaving_lost and tenant_obj is not None:
            # Plan C4: a found parcel is billed again (freight re-debited + DN) before any other
            # re-price, so a following RTO is billed as usual on top of it.
            found_result = await reprice.apply(
                current, tenant_obj, RepriceChange(reason=ChargeAdjustmentReason.LOST_FOUND), user
            )
            if found_result.changed:
                diff["lost_found"] = found_result.activity_diff()["repricing"]
        if price_change is not None and tenant_obj is not None:
            reprice_result = await reprice.apply(current, tenant_obj, price_change, user)
            if reprice_result.changed:
                diff.update(reprice_result.activity_diff())
                diff["payment_details"] = "Updated Financials"

        # E-Way Bill Strict Validation on Update
        if (
            current.payment_details
            and current.payment_details.shipment_total_value
            >= EWAY_BILL_MANDATORY_THRESHOLD
        ):
            eway_bill_numbers = current.payment_details.eway_bill_numbers or []
            has_eway_bill_number = any(bool(eb.strip()) for eb in eway_bill_numbers)

            # Combine current documents (excluding those to delete) and new documents
            docs_to_check = [
                d for d in current.documents if d not in documents_to_delete
            ] + documents_to_add
            has_eway_bill_doc = any(
                d.document_type == DocumentType.EWAY_BILL for d in docs_to_check
            )

            if not (has_eway_bill_number or has_eway_bill_doc):
                raise HTTPException(
                    status_code=400,
                    detail=f"E-Way bill is mandatory for shipments with value >= {EWAY_BILL_MANDATORY_THRESHOLD} INR. Provide either eway_bill_numbers or upload an EWAY_BILL document.",
                )
            if has_eway_bill_number:
                for eway in eway_bill_numbers:
                    if not re.match(r"^\d{12}$", eway.strip()):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid E-Way bill format: '{eway}'. Must be exactly 12 digits.",
                        )

        # 10. Create Activity Log
        activity_type = ActivityType.INFO_UPDATE
        if "status" in diff:
            activity_type = ActivityType.STATUS_CHANGE
        elif not diff and payload.comment:
            activity_type = ActivityType.COMMENT

        summary_list = []
        if payload.status == PickupStatus.COMPLETED and current.delivery_otp:
            summary_list.append(
                f"Delivered — OTP Verified (Received by: {current.pod_received_by})"
            )
        elif payload.status == PickupStatus.QC_FAILED and "status" in diff:
            summary_list.append("Doorstep QC Failed — Return Rejected at Pickup")
        elif "status" in diff and payload.status:
            summary_list.append(f"Status: {payload.status.value}")
        if is_raising_exception and current.ndr_reason is not None:
            summary_list.append(f"Exception Raised: {current.ndr_reason.value}")
        if cancel_converted:
            summary_list.append(CANCEL_TO_RTO_COMMENT)
        if "packages" in diff:
            summary_list.append("Packages Updated")
        if "repricing" in diff:
            summary_list.append("Charges Updated")
        if "documents" in diff:
            summary_list.append("Documents Updated")
        if not summary_list:
            summary_list.append("Details Updated")

        is_public_activity = bool(
            payload.is_public or payload.status == PickupStatus.COMPLETED
        )

        activity = ShipmentActivity(
            pickup_id=shipment_id,
            user_id=user.id,
            activity_type=activity_type,
            summary=", ".join(summary_list),
            comment=payload.comment,
            is_public=is_public_activity,
            diff=diff,
        )

        # 11. Save Everything
        updated_shipment = await self.shipment_repo.update_shipment_with_activity(
            shipment=current,
            activity=activity,
            packages_to_add=packages_to_add,
            packages_to_delete=packages_to_delete,
            documents_to_add=documents_to_add,
            documents_to_delete=documents_to_delete,
            new_pickup_address=new_pickup_addr,
            new_delivery_address=new_delivery_addr,
        )
        if is_raising_exception:
            updated_shipment = await self.enforce_ndr_attempt_limit(
                updated_shipment, actor=user, tenant_id=tenant_id, held_from=original_status
            )
        if is_entering_rto:
            rto_diff = await self.apply_rto_charges(updated_shipment, tenant_id, actor=user)
            if rto_diff:
                activity.diff = dict(activity.diff or {}, **rto_diff)
                self.shipment_repo.session.add(activity)
        if is_cancelling:
            await self.refund_prepaid_freight(updated_shipment, tenant_id, actor=user)
        elif is_pickup_rejected:
            await self.refund_prepaid_freight(
                updated_shipment,
                tenant_id,
                actor=user,
                reason=ChargeAdjustmentReason.PICKUP_REJECTION_REFUND,
            )
        elif is_entering_lost:
            # Plan C4: a lost parcel refunds the net freight (+ CN), never billed an RTO leg.
            await self.refund_prepaid_freight(
                updated_shipment, tenant_id, actor=user, reason=ChargeAdjustmentReason.LOST
            )
        await self.shipment_repo.session.commit()
        if is_raising_exception:
            creator = await self.shipment_repo.session.get(
                User, updated_shipment.created_by_user_id
            )
            await notify_ndr_raised(
                merchant_email=creator.email if creator else None,
                tracking_id=updated_shipment.tracking_id,
                reason=updated_shipment.ndr_reason.value if updated_shipment.ndr_reason else None,
                remark=updated_shipment.ndr_remark,
            )
        return updated_shipment

    @staticmethod
    def _assert_customer_patch_scope(payload: PickupUpdate) -> None:
        """
        Customers edit their own order (B9) but never operations fields (status, NDR,
        POD, OTP, exception charges); those stay with tenant staff.

        Raises:
            HTTPException(403): a forbidden field is present in the PATCH body.
        """
        forbidden = sorted(CUSTOMER_FORBIDDEN_PATCH_FIELDS & payload.model_fields_set)
        if forbidden:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only Logismart staff can change: {', '.join(forbidden)}.",
            )

    @staticmethod
    def is_after_pickup(
        shipment: PickupRequest, held_from: Optional[PickupStatus] = None
    ) -> bool:
        """
        True once the parcel has physically left the merchant: in transit, RTO, delivered,
        or on an exception raised after pickup (A-21: decided by the status it was held
        from; legacy rows without it fall back to the reason-only NPR rule).
        """
        if shipment.status in AFTER_PICKUP_STATUSES:
            return True
        if shipment.status != PickupStatus.EXCEPTION:
            return False
        if held_from is not None:
            return ndr_rules.is_picked_up(held_from)
        return not ndr_rules.is_pickup_stage(shipment.ndr_reason, shipment.shipment_type)

    def _convert_post_pickup_cancel(
        self,
        current: PickupRequest,
        payload: PickupUpdate,
        held_from: Optional[PickupStatus] = None,
    ) -> Tuple[PickupUpdate, bool]:
        """
        B10 / DO1 `cancel-forward-order`: a "cancel" after pickup becomes an RTO (RTO billed,
        no refund) instead of a 400. Cancels before pickup are untouched.

        Returns:
            The (possibly rewritten) payload and whether the conversion happened.
        """
        if payload.status != PickupStatus.CANCELLED or not self.is_after_pickup(
            current, held_from
        ):
            return payload, False
        return payload.model_copy(update={"status": PickupStatus.RTO_INITIATED}), True

    @staticmethod
    def _apply_payment_compliance_fields(
        payment: PaymentDetails, payload: PickupUpdate
    ) -> None:
        """
        Copies the non-price payment fields of a PATCH (invoice / e-way bill / HSN / goods
        split). Price inputs (COD, declared total, payment mode, shipping-to-COD) are written
        only by `RepricingService.apply`, and the price columns are never client-controlled.
        """
        sent = payload.payment_details.model_dump(exclude_unset=True)
        for key in PAYMENT_COMPLIANCE_FIELDS & sent.keys():
            setattr(payment, key, sent[key])

    # --- 3b. Delivery Exception (NDR) helpers ---

    @staticmethod
    def _validate_cod_amount(
        current: PickupRequest,
        payload: PickupUpdate,
        cod_amount: float,
        total_value: float,
    ) -> None:
        """
        Validates the goods COD amount when COD-related payment fields are edited.
        A-01: `cod_amount` is the goods COD only (shipping is added on top by the backend
        when `add_shipping_to_cod`), so it is capped at the declared goods value.

        Raises:
            HTTPException(400): COD amount is <= 0 or above the declared value.
        """
        if cod_amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="COD amount must be greater than 0 when COD is enabled.",
            )
        effective_goods = to_money(cod_amount)
        if (
            current.payment_details
            and to_money(cod_amount) == to_money(current.payment_details.cod_amount)
            and cod_payout._freight_inside_cod(current.payment_details)
        ):
            effective_goods = cod_payout.cod_goods_amount(current.payment_details)
        elif (
            current.payment_details
            and current.payment_details.add_shipping_to_cod
            and cod_payout._freight_inside_cod(current.payment_details)
            and to_money(cod_amount) > to_money(total_value)
            and to_money(cod_amount) - to_money(current.payment_details.total_logistics_cost) <= to_money(total_value)
        ):
            effective_goods = to_money(cod_amount) - to_money(current.payment_details.total_logistics_cost)

        if effective_goods > to_money(total_value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="COD amount cannot exceed shipment total value.",
            )

    @staticmethod
    def _assert_service_scope(actor: Optional[User], is_b2b: bool) -> None:
        """
        Customers may only book in the flow(s) their `service_scope` allows
        (B2C-only can't book B2B cargo and vice versa). Tenant staff are exempt.

        Raises:
            HTTPException(403): booking outside the customer's scope.
        """
        if actor is None or is_tenant_staff(actor):
            return
        scope = actor.service_scope or ServiceScope.B2C
        if scope == ServiceScope.BOTH:
            return
        if is_b2b and scope != ServiceScope.B2B:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is enabled for B2C parcels only; B2B cargo bookings are not allowed.",
            )
        if not is_b2b and scope != ServiceScope.B2C:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is enabled for B2B cargo only; B2C parcel bookings are not allowed.",
            )

    @staticmethod
    def assert_label_available(shipment: PickupRequest) -> None:
        """Shipping labels are never printed for cancelled shipments (400)."""
        if shipment.status == PickupStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Labels are not available for a cancelled shipment.",
            )

    @staticmethod
    def assert_invoice_available(shipment: PickupRequest) -> None:
        """
        A prepaid GST freight invoice exists only for live, merchant-billed
        shipments: not for CANCELLED ones, and not for TO_PAY (the consignee
        pays the freight at delivery). Raises 400 otherwise.
        """
        if shipment.status == PickupStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invoices are not available for a cancelled shipment.",
            )
        payment = shipment.payment_details
        if payment and not is_wallet_billed(payment):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This shipment's freight is not billed to the merchant wallet (TO_PAY / Freight on Delivery or staff POSTPAID account billing), so no merchant invoice is issued.",
            )

    @staticmethod
    def release_for_cancellation(shipment: PickupRequest) -> Dict[str, Any]:
        """
        Detaches a cancelled shipment from its Pickup Request (manifest) so the
        run-sheet no longer expects it.

        Returns:
            Diff entries for the audit activity.
        """
        if shipment.manifest_id is None:
            return {}
        old_manifest = str(shipment.manifest_id)
        shipment.manifest_id = None
        return {"manifest_id": {"old": old_manifest, "new": None}}

    async def _sync_manifest_after_detach(
        self,
        manifest_id: Optional[uuid.UUID],
        detached_shipment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """
        D-11: Recomputes `manifest.total_boxes` when a linked shipment is cancelled, and
        auto-cancels a SCHEDULED pickup request once all of its linked shipments are gone.
        """
        if manifest_id is None:
            return
        manifest_repo = ManifestRepository(self.shipment_repo.session)
        manifest = await manifest_repo.get_manifest_by_id(
            manifest_id, tenant_id, for_update=True
        )
        if manifest is None or manifest.status not in (
            ManifestStatus.SCHEDULED,
            ManifestStatus.OUT_FOR_PICKUP,
        ):
            return
        remaining = [
            s
            for s in (manifest.pickups or [])
            if s.id != detached_shipment_id
            and s.manifest_id == manifest.id
            and s.status not in (
                PickupStatus.CANCELLED,
                PickupStatus.QC_FAILED,
                PickupStatus.REJECTED_AT_PICKUP,
            )
        ]
        if not remaining:
            manifest.total_boxes = 0
            if manifest.status == ManifestStatus.SCHEDULED:
                manifest.status = ManifestStatus.CANCELED
        elif not manifest.is_blind_pickup:
            manifest.total_boxes = sum(
                sum((p.box_count or 1) for p in (s.packages or []))
                or (s.estimated_box_count or 1)
                for s in remaining
            )
        self.shipment_repo.session.add(manifest)

    @staticmethod
    def _validate_exception_raise(
        reason: Optional[NdrExceptionReason], payload: PickupUpdate
    ) -> None:
        """
        Validates the ops-entered inputs required by specific reasons.

        FREIGHT_COLLECTION / ADDITIONAL_CHARGES need a positive charge_amount;
        WEIGHT_DISCREPANCY needs a measured weight or a positive charge_amount.

        Raises:
            HTTPException(400): when a required input is missing.
        """
        has_charge = bool(payload.charge_amount and payload.charge_amount > 0)
        if reason in ndr_rules.CHARGE_TXN_TYPES and not has_charge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"charge_amount (> 0) is required to raise a {reason.value} exception.",
            )
        if (
            reason == NdrExceptionReason.WEIGHT_DISCREPANCY
            and payload.measured_weight_kg is None
            and not has_charge
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="measured_weight_kg or charge_amount is required to raise a WEIGHT_DISCREPANCY exception.",
            )

    @staticmethod
    def _record_exception_raise(
        shipment: PickupRequest, payload: PickupUpdate
    ) -> Dict[str, Any]:
        """
        Applies the bookkeeping of a freshly raised exception to the shipment.

        Sets `exception_raised_at` (server-side aging), the agent remark and the
        charge to acknowledge, and increments `ndr_attempt_count` for failed
        delivery / pickup attempts.

        Returns:
            The `ndr_raise` audit payload stored in the activity diff.
        """
        shipment.exception_raised_at = _utc_now_naive()
        if payload.ndr_remark is not None:
            shipment.ndr_remark = payload.ndr_remark.strip() or None
        shipment.charge_amount = (
            round(float(payload.charge_amount), MONEY_DECIMALS)
            if payload.charge_amount
            else None
        )
        if ndr_rules.counts_as_attempt(shipment.ndr_reason):
            shipment.ndr_attempt_count = int(shipment.ndr_attempt_count or 0) + 1
        return {
            "reason": shipment.ndr_reason.value if shipment.ndr_reason else None,
            "attempt": shipment.ndr_attempt_count,
            "remark": shipment.ndr_remark,
            "charge_amount": shipment.charge_amount,
            "measured_weight_kg": payload.measured_weight_kg,
        }

    @staticmethod
    def _clear_exception_tracking(shipment: PickupRequest) -> None:
        """Clears per-exception fields once a shipment leaves EXCEPTION (attempts and remark are kept)."""
        shipment.exception_raised_at = None
        shipment.charge_amount = None

    @staticmethod
    def ensure_delivery_otp(shipment: PickupRequest) -> Dict[str, Any]:
        """
        Gives a shipment on its way to the consignee a 6-digit delivery OTP if it has none
        (D-04b: every path into In transit / Out for delivery, including an NDR resume, so a
        Delivered mark can always be OTP-verified). Uses `secrets`, not `random`.

        Returns:
            The `delivery_otp` diff entry when an OTP was created, else {}.
        """
        if shipment.status not in OTP_REQUIRED_STATUSES or shipment.delivery_otp:
            return {}
        shipment.delivery_otp = str(DELIVERY_OTP_MIN + secrets.randbelow(DELIVERY_OTP_SPAN))
        return {"delivery_otp": {"old": None, "new": shipment.delivery_otp}}

    @staticmethod
    def _assert_status_change_role(
        user: User, new_status: PickupStatus, original_status: PickupStatus, cancel_converted: bool
    ) -> None:
        """
        A-22: LOST (full refund + CN), leaving LOST (re-bill) and a manual RTO (RTO charge)
        are owner/admin decisions; operations / support staff can't trigger them. A shipper's
        own post-pickup cancel that converts to RTO is their consent and stays allowed.

        Raises:
            HTTPException(403): an operations/support user attempts one of these moves.
        """
        if is_tenant_admin(user) or user.role == UserRole.customer:
            return
        if new_status == PickupStatus.RTO_INITIATED and cancel_converted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=POST_PICKUP_CANCEL_RTO_DETAIL,
            )
        is_manual_rto = new_status == PickupStatus.RTO_INITIATED
        touches_lost = LOST_STATUS in (new_status, original_status) and new_status != original_status
        if is_manual_rto or touches_lost:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ADMIN_ONLY_STATUS_DETAIL,
            )

    @staticmethod
    def _assert_exception_exit(
        current: PickupRequest, new_status: PickupStatus, held_from: Optional[PickupStatus]
    ) -> None:
        """
        D-04: a manual move out of EXCEPTION must return the parcel to the stage it was held
        from (or a failed Out-for-delivery may go straight out again), never forward from
        before pickup or from the RTO leg. RTO / cancel / LOST keep their own rules.

        Raises:
            HTTPException(400): the target contradicts the parcel's stage.
        """
        if new_status in EXCEPTION_EXIT_SPECIAL_STATUSES:
            return
        expected = ndr_rules.resume_status(
            current.ndr_reason, current.shipment_type, current.manifest_id is not None, held_from
        )
        allowed = {expected}
        if expected == PickupStatus.IN_TRANSIT:
            allowed.add(PickupStatus.OUT_FOR_DELIVERY)
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This parcel was on hold from {held_from.value if held_from else 'an earlier stage'}; "
                    f"it can only resume to {expected.value}."
                ),
            )

    async def _replay_or_reject_duplicate_raise(
        self, current: PickupRequest, payload: PickupUpdate
    ) -> Optional[PickupRequest]:
        """
        D-05: a second "raise exception" on a shipment that is already on hold.

        The same reason is a retried request (rider double tap on a flaky network): it is
        answered with the current shipment and changes nothing, so the attempt counter can't
        jump by two and trigger an early auto-RTO. A different reason is refused (resolve
        the current exception first).

        Returns:
            The unchanged shipment for a replay, or None when this is not a duplicate raise.

        Raises:
            HTTPException(409): a different reason while already on hold.
        """
        if current.status != PickupStatus.EXCEPTION or payload.status != PickupStatus.EXCEPTION:
            return None
        requested = payload.ndr_reason or current.ndr_reason
        if ndr_rules.canonical_reason(requested) != ndr_rules.canonical_reason(current.ndr_reason):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This shipment is already on hold for {current.ndr_reason.value if current.ndr_reason else 'an exception'}. "
                    "Resolve that exception before raising a new one."
                ),
            )
        await self.shipment_repo.session.commit()  # nothing changed; releases the row lock
        return current

    async def _locked_for_reprice(
        self, shipment: PickupRequest, tenant_id: uuid.UUID
    ) -> Tuple[RepricingService, Optional[Tenant]]:
        """
        Flushes pending header changes, then takes the row lock RepricingService.apply needs
        (re-entrant inside the caller's transaction, so already-locked rows are fine).
        """
        session = self.shipment_repo.session
        await session.flush()
        reprice = RepricingService(session)
        await reprice.load_shipment(shipment.id, tenant_id, for_update=True)
        return reprice, await session.get(Tenant, tenant_id)

    async def reprice_no_commit(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        change: RepriceChange,
        actor: Optional[User],
    ) -> RepriceResult:
        """
        Re-prices an already-loaded shipment inside the caller's transaction (NDR actions,
        dispatch). Flushes pending header edits, row-locks, then RepricingService.apply.
        No permission checks, no activity, no commit.
        """
        reprice, _ = await self._locked_for_reprice(shipment, tenant.id)
        return await reprice.apply(shipment, tenant, change, actor)

    async def refund_prepaid_freight(
        self,
        shipment: PickupRequest,
        tenant_id: uuid.UUID,
        *,
        actor: Optional[User] = None,
        reason: ChargeAdjustmentReason = ChargeAdjustmentReason.CANCELLATION,
    ) -> Optional[RepriceResult]:
        """
        Refunds a cancelled / refused-at-pickup shipment: the net freight debited (never
        more, H-1) goes back to the creator's wallet with a CREDIT_NOTE for exactly the
        refunded amount (plan B3). Wallet-billed shipments only (B16); TO_PAY and staff
        POSTPAID were never debited. Does not commit.
        """
        if shipment.payment_details is None or not is_wallet_billed(shipment):
            return None
        reprice, tenant = await self._locked_for_reprice(shipment, tenant_id)
        if tenant is None:
            return None
        return await reprice.refund_all(shipment, tenant, reason, actor)

    async def apply_rto_charges(
        self,
        shipment: PickupRequest,
        tenant_id: uuid.UUID,
        *,
        actor: Optional[User] = None,
        waive_rto_charge: bool = False,
    ) -> Dict[str, Any]:
        """
        Single RTO billing path shared by the admin PATCH to RTO_INITIATED, a post-pickup
        cancel, the merchant's RETURN_TO_ORIGIN action and the automatic RTO after the last
        failed attempt. RepricingService adds the RTO leg on the billing basis (an earlier
        measurement is kept), debits the wallet-billed delta (may go negative) with a
        DEBIT_NOTE, and is a no-op when the bill already carries the RTO leg. With
        `waive_rto_charge` (Logismart liable, plan B6) no RTO leg is billed. No permission
        checks, no commit.

        Returns:
            `rto_freight` + `repricing` diff entries for the audit activity (empty when unchanged).
        """
        if shipment.payment_details is None:
            return {}
        reprice, tenant = await self._locked_for_reprice(shipment, tenant_id)
        if tenant is None:
            return {}
        rto_diff = await self._reverse_cod_fee_on_rto(reprice, shipment, tenant, actor)
        result = await reprice.apply(
            shipment,
            tenant,
            RepriceChange(
                reason=ChargeAdjustmentReason.RTO,
                is_rto=not waive_rto_charge,
                waive_rto_charge=waive_rto_charge,
                remark=RTO_FREIGHT_REMARK_TEMPLATE.format(tracking_id=shipment.tracking_id),
            ),
            actor,
        )
        if not result.changed:
            if waive_rto_charge:
                rto_diff["rto_charge_waived"] = True
            return rto_diff
        wallet_debit = -result.wallet_delta if result.wallet_delta < ZERO_MONEY else ZERO_MONEY
        rto_diff["rto_freight"] = {
            "old_total": money_to_float(result.old_total),
            "new_total": money_to_float(result.new_total),
            "rto_surcharge": (result.new_breakdown or {}).get(RTO_SURCHARGE_KEY, 0.0),
            "wallet_debit": money_to_float(wallet_debit),
            "waived": waive_rto_charge,
        }
        rto_diff.update(result.activity_diff())
        return rto_diff

    @staticmethod
    async def _reverse_cod_fee_on_rto(
        reprice: RepricingService,
        shipment: PickupRequest,
        tenant: Tenant,
        actor: Optional[User],
    ) -> Dict[str, Any]:
        """
        Plan C2 / D50: an RTO parcel never collects cash, so its COD fee is reversed with its
        own CREDIT_NOTE (before the RTO leg's DEBIT_NOTE) and the COD state becomes FAILED_RTO.
        The RTO leg already on the bill is kept as is, so this step only drops the fee; once
        the status is an RTO status RepricingService never charges the fee again. No-op for
        non-COD shipments and when the fee is already gone (`changed=False`).

        Returns:
            A `cod_fee_reversal` diff entry (empty when nothing changed).
        """
        payment = shipment.payment_details
        if payment is None or not payment.is_cod:
            return {}
        payment.cod_remittance_status = CodRemittanceStatus.FAILED_RTO
        has_rto_leg = to_money((payment.pricing_breakdown or {}).get(RTO_SURCHARGE_KEY)) > ZERO_MONEY
        result = await reprice.apply(
            shipment,
            tenant,
            RepriceChange(
                reason=ChargeAdjustmentReason.COD_FEE_REVERSAL,
                waive_cod_fee=True,
                is_rto=has_rto_leg,
            ),
            actor,
        )
        if not result.changed:
            return {}
        return {"cod_fee_reversal": result.activity_diff()["repricing"]}

    async def enforce_ndr_attempt_limit(
        self,
        shipment: PickupRequest,
        *,
        actor: User,
        tenant_id: uuid.UUID,
        held_from: Optional[PickupStatus] = None,
    ) -> PickupRequest:
        """
        Auto-resolves a shipment that reached MAX_NDR_ATTEMPTS failed attempts:
        forward deliveries go to RTO_INITIATED, pickup-stage (NPR) exceptions
        are CANCELLED with a prepaid-freight refund; nothing is forced on the RTO leg
        or for a reverse parcel already picked up (A-21). Writes an audit activity.
        Does not commit.

        Args:
            held_from: Status when the exception was raised (looked up when None).

        Returns:
            The (possibly) updated, fully loaded shipment.
        """
        if shipment.status != PickupStatus.EXCEPTION:
            return shipment
        if held_from is None:
            held_from = await self.shipment_repo.get_held_from_status(shipment.id, tenant_id)
        forced_status = ndr_rules.attempt_limit_outcome(
            shipment.ndr_reason, shipment.shipment_type, shipment.ndr_attempt_count, held_from
        )
        if forced_status is None:
            return shipment
        ShipmentLifecycleMachine.validate_transition(shipment.status, forced_status)

        old_reason = shipment.ndr_reason.value if shipment.ndr_reason else None
        shipment.status = forced_status
        shipment.ndr_reason = None
        self._clear_exception_tracking(shipment)
        diff: Dict[str, Any] = {
            "status": {"old": PickupStatus.EXCEPTION.value, "new": forced_status.value},
            "ndr_reason": {"old": old_reason, "new": None},
            "ndr_auto_resolution": forced_status.value,
        }
        if forced_status == PickupStatus.CANCELLED:
            detached_manifest_id = shipment.manifest_id
            diff.update(self.release_for_cancellation(shipment))
            await self._sync_manifest_after_detach(detached_manifest_id, shipment.id, tenant_id)
        else:
            diff.update(await self.apply_rto_charges(shipment, tenant_id, actor=actor))
        label = "Auto-RTO" if forced_status == PickupStatus.RTO_INITIATED else "Auto-cancelled"
        activity = ShipmentActivity(
            pickup_id=shipment.id,
            user_id=actor.id,
            activity_type=ActivityType.STATUS_CHANGE,
            summary=f"{label} after {ndr_rules.MAX_NDR_ATTEMPTS} failed attempts",
            comment=f"Maximum of {ndr_rules.MAX_NDR_ATTEMPTS} attempts reached.",
            is_public=True,
            diff=diff,
        )
        updated = await self.shipment_repo.update_shipment_with_activity(
            shipment=shipment,
            activity=activity,
            packages_to_add=[],
            packages_to_delete=[],
            documents_to_add=[],
            documents_to_delete=[],
        )
        if forced_status == PickupStatus.CANCELLED:
            await self.refund_prepaid_freight(updated, tenant_id, actor=actor)
        return updated

    async def cancel_shipment(
        self, shipment_id: uuid.UUID, user: User, tenant_id: uuid.UUID
    ) -> PickupRequest:
        """
        Cancel a shipment. Only allowed if status is OPEN or ASSIGNED.
        Automatically refunds PREPAID freight to the shipment creator's UserWallet.
        """
        assert_can_manage_shipments_or_pickups(user, "cancel shipments")
        # Row lock first (H-4, J55): of two concurrent cancels the second waits, then sees the
        # committed CANCELLED status and is refused, so freight is refunded exactly once.
        await RepricingService(self.shipment_repo.session).load_shipment(
            shipment_id, tenant_id, for_update=True
        )
        shipment = await self.shipment_repo.get_shipment_full_details(
            shipment_id, tenant_id
        )
        if not shipment or shipment.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        is_admin = is_tenant_staff(user)
        if not is_admin and shipment.created_by_user_id != user.id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        if shipment.status in TERMINAL_STATUSES:
            # H-10: delivered / terminal shipments are never cancelled (use a return or a claim).
            raise HTTPException(
                status_code=400,
                detail=f"Shipment cannot be cancelled from status {shipment.status.value}",
            )
        held_from = (
            await self.shipment_repo.get_held_from_status(shipment_id, tenant_id)
            if shipment.status == PickupStatus.EXCEPTION
            else None
        )
        if self.is_after_pickup(shipment, held_from):
            return await self._cancel_after_pickup_as_rto(shipment, user, tenant_id)
        if shipment.status not in [
            PickupStatus.DRAFT,
            PickupStatus.OPEN,
            PickupStatus.ASSIGNED,
        ]:
            raise HTTPException(
                status_code=400,
                detail=f"Shipment cannot be cancelled from status {shipment.status.value}",
            )

        detached_manifest_id = shipment.manifest_id
        shipment.status = PickupStatus.CANCELLED
        cancel_diff: Dict[str, Any] = {
            "status": PickupStatus.CANCELLED.value,
            **self.release_for_cancellation(shipment),
        }
        await self._sync_manifest_after_detach(detached_manifest_id, shipment.id, tenant_id)

        activity = ShipmentActivity(
            pickup_id=shipment.id,
            user_id=user.id,
            activity_type=ActivityType.STATUS_CHANGE,
            summary="Shipment Cancelled",
            comment="Shipment was cancelled by user.",
            is_public=True,
            diff=cancel_diff,
        )

        updated_shipment = await self.shipment_repo.update_shipment_with_activity(
            shipment=shipment,
            activity=activity,
            packages_to_add=[],
            packages_to_delete=[],
            documents_to_add=[],
            documents_to_delete=[],
        )

        # Refund the net freight debited (wallet-billed only) with a CN = the refund
        await self.refund_prepaid_freight(updated_shipment, tenant_id, actor=user)

        await self.shipment_repo.session.commit()
        return updated_shipment

    async def _cancel_after_pickup_as_rto(
        self, shipment: PickupRequest, user: User, tenant_id: uuid.UUID
    ) -> PickupRequest:
        """
        Plan B10 / DO1 `cancel-forward-order`: once picked up, a cancel becomes an RTO. The
        RTO leg is billed through RepricingService; nothing is refunded. Only the shipper or
        an Owner/Admin may initiate a manual RTO.
        """
        if not is_tenant_admin(user) and user.role != UserRole.customer:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=POST_PICKUP_CANCEL_RTO_DETAIL,
            )
        old_status = shipment.status
        shipment.status = PickupStatus.RTO_INITIATED
        shipment.ndr_reason = None
        self._clear_exception_tracking(shipment)
        diff: Dict[str, Any] = {
            "status": {"old": old_status.value, "new": PickupStatus.RTO_INITIATED.value},
            "cancel_converted_to_rto": True,
        }
        diff.update(await self.apply_rto_charges(shipment, tenant_id, actor=user))
        activity = ShipmentActivity(
            pickup_id=shipment.id,
            user_id=user.id,
            activity_type=ActivityType.STATUS_CHANGE,
            summary="Cancelled after pickup — Return to Origin",
            comment=CANCEL_TO_RTO_COMMENT,
            is_public=True,
            diff=diff,
        )
        updated = await self.shipment_repo.update_shipment_with_activity(
            shipment=shipment,
            activity=activity,
            packages_to_add=[],
            packages_to_delete=[],
            documents_to_add=[],
            documents_to_delete=[],
        )
        await self.shipment_repo.session.commit()
        return updated

    async def update_appointment(
        self,
        shipment_id: uuid.UUID,
        payload: AppointmentUpdate,
        user: User,
        tenant_id: uuid.UUID,
    ) -> PickupRequest:
        """
        Updates the delivery appointment for a shipment, logs history, and clears NDR state if applicable.
        """
        assert_not_read_only(user, "update delivery appointments")
        shipment = await self.shipment_repo.get_shipment_full_details(
            shipment_id, tenant_id
        )
        if not shipment or shipment.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        is_admin = is_tenant_staff(user)
        if not is_admin and shipment.created_by_user_id != user.id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        if shipment.status not in [
            PickupStatus.DRAFT,
            PickupStatus.OPEN,
            PickupStatus.ASSIGNED,
            PickupStatus.IN_TRANSIT,
            PickupStatus.EXCEPTION,
        ]:
            raise HTTPException(
                status_code=400,
                detail="Shipment must be DRAFT, OPEN, ASSIGNED, IN_TRANSIT, or EXCEPTION to update appointment",
            )

        is_appointment_exception = shipment.status == PickupStatus.EXCEPTION
        if is_appointment_exception and (
            ndr_rules.canonical_reason(shipment.ndr_reason)
            != NdrExceptionReason.APPOINTMENT_NEEDED
        ):
            reason = shipment.ndr_reason.value if shipment.ndr_reason else "UNKNOWN"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This shipment is on hold for {reason}. Resolve it from Delivery "
                    "Exceptions; booking an appointment only clears APPOINTMENT_NEEDED."
                ),
            )

        diff: Dict[str, Any] = {}
        for k, v in payload.model_dump(exclude_unset=True).items():
            old_val = getattr(shipment, k)
            if old_val != v:
                diff[k] = {
                    "old": (
                        old_val.isoformat()
                        if hasattr(old_val, "isoformat")
                        else old_val
                    ),
                    "new": v.isoformat() if hasattr(v, "isoformat") else v,
                }
                setattr(shipment, k, v)

        if is_appointment_exception:
            # Same semantics as POST /exceptions/{id}/actions BOOK_APPOINTMENT.
            held_from = await self.shipment_repo.get_held_from_status(shipment.id, tenant_id)
            resumed = ndr_rules.resume_status(
                shipment.ndr_reason,
                shipment.shipment_type,
                shipment.manifest_id is not None,
                held_from,
            )
            diff["ndr_action"] = NdrAction.BOOK_APPOINTMENT.value
            diff["status"] = {"old": PickupStatus.EXCEPTION.value, "new": resumed.value}
            diff["ndr_reason"] = {
                "old": NdrExceptionReason.APPOINTMENT_NEEDED.value,
                "new": None,
            }
            shipment.status = resumed
            shipment.ndr_reason = None
            self._clear_exception_tracking(shipment)
            diff.update(self.ensure_delivery_otp(shipment))

        activity = ShipmentActivity(
            pickup_id=shipment.id,
            user_id=user.id,
            activity_type=(
                ActivityType.STATUS_CHANGE if is_appointment_exception else ActivityType.INFO_UPDATE
            ),
            summary="Appointment Updated",
            comment="Updated via API",
            is_public=False,
            diff=diff,
        )

        updated_shipment = await self.shipment_repo.update_shipment_with_activity(
            shipment=shipment,
            activity=activity,
            packages_to_add=[],
            packages_to_delete=[],
            documents_to_add=[],
            documents_to_delete=[],
        )
        await self.shipment_repo.session.commit()
        return updated_shipment

    async def audit_shipment_weight(
        self,
        shipment_id: uuid.UUID,
        audited_weight_kg: float,
        user: User,
        tenant: Tenant,
        *,
        override_total_price: Optional[float] = None,
    ) -> PickupRequest:
        """
        Legacy "Audit Scale (kg)" entry, kept for `/audit-weight`: a weight-only hub
        measurement. The declared boxes keep their sizes (weights scaled to the audited
        total), so the bill never drops below the declared volumetric (plan B4).
        """
        if audited_weight_kg <= 0:
            raise HTTPException(
                status_code=400,
                detail="Audited weight must be greater than 0.0 KG.",
            )
        updated, _ = await self.record_measurement(
            shipment_id,
            user,
            tenant,
            MeasurementInput(
                source=MeasurementSource.HUB,
                weight_only_kg=to_money(audited_weight_kg),
                override_total_price=(
                    to_money(override_total_price)
                    if override_total_price is not None
                    else None
                ),
            ),
        )
        return updated

    async def record_measurement(
        self,
        shipment_id: uuid.UUID,
        user: User,
        tenant: Tenant,
        measurement: MeasurementInput,
        *,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[PickupRequest, RepriceResult]:
        """
        Records a measured parcel (rider Actual pieces, hub scale or admin) and re-bills the
        shipment on it, both ways (plan B4): up = debit + DEBIT_NOTE, down = refund + CREDIT_NOTE
        for wallet-billed shipments; TO_PAY moves the freight to collect. The merchant can
        dispute afterwards through Weight Mismatch. Commits.

        Returns:
            The fully loaded shipment and the re-price result.
        """
        assert_can_manage_shipments_or_pickups(user, "record parcel measurements")
        if user.role not in STAFF_EDITOR_ROLES:
            raise HTTPException(
                status_code=403, detail="Only operations or admin users can record measurements"
            )
        if measurement.override_total_price is not None and user.role not in (
            UserRole.owner,
            UserRole.admin,
        ):
            raise HTTPException(
                status_code=403,
                detail="Only Tenant Owners and Admins can override the final shipment price.",
            )
        assert_not_read_only(user, "record parcel measurements")
        reprice = RepricingService(self.shipment_repo.session)
        await reprice.load_shipment(shipment_id, tenant.id, for_update=True)
        shipment = await self.shipment_repo.get_shipment_full_details(shipment_id, tenant.id)
        if not shipment or shipment.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Shipment not found")
        if shipment.status in (
            PickupStatus.CANCELLED,
            PickupStatus.QC_FAILED,
            PickupStatus.REJECTED_AT_PICKUP,
            PickupStatus.LOST,
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot record a measurement on a {shipment.status.value} shipment.",
            )

        result = await self.measure_no_commit(
            shipment, tenant, measurement, user, idempotency_key=idempotency_key
        )
        activity = ShipmentActivity(
            pickup_id=shipment.id,
            user_id=user.id,
            activity_type=ActivityType.INFO_UPDATE,
            summary=self._measurement_summary(measurement, result),
            comment=measurement.remark or self._measurement_summary(measurement, result),
            is_public=True,
            diff={**self.weight_audit_diff(result), **result.activity_diff()},
        )
        updated = await self.shipment_repo.update_shipment_with_activity(
            shipment=shipment,
            activity=activity,
            packages_to_add=[],
            packages_to_delete=[],
            documents_to_add=[],
            documents_to_delete=[],
        )
        await self.shipment_repo.session.commit()
        if result.changed and not result.replayed and result.wallet_delta < ZERO_MONEY:
            creator = await self.shipment_repo.session.get(
                User, updated.created_by_user_id
            )
            await notify_weight_debit(
                merchant_email=creator.email if creator else None,
                tracking_id=updated.tracking_id,
                old_weight_kg=money_to_float(result.old_chargeable_weight),
                new_weight_kg=money_to_float(result.new_chargeable_weight),
                debit_inr=money_to_float(-result.wallet_delta),
            )
        return updated, result

    async def measure_no_commit(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        measurement: MeasurementInput,
        actor: Optional[User],
        *,
        idempotency_key: Optional[str] = None,
    ) -> RepriceResult:
        """
        Shared measurement path (hub audit, rider pickup, NDR ACCEPT_WEIGHT): re-prices via
        RepricingService and keeps the Weight Mismatch row in step. The shipment must already
        be row-locked by the caller's transaction. No permission checks, no activity, no commit.
        """
        reprice, _ = await self._locked_for_reprice(shipment, tenant.id)
        result = await reprice.record_measurement(
            shipment, tenant, measurement, actor, idempotency_key=idempotency_key
        )
        if result.changed and not result.replayed:
            delhivery_service = DelhiveryModulesService(
                DelhiveryModulesRepository(self.shipment_repo.session)
            )
            await delhivery_service.record_weight_audit_dispute(
                shipment=shipment,
                old_weight_kg=money_to_float(result.old_chargeable_weight),
                audited_weight_kg=money_to_float(result.new_chargeable_weight),
                old_total=money_to_float(result.old_total),
                new_total=money_to_float(result.new_total),
                charged_dims=self._measured_dims_label(measurement),
                evidence_urls=measurement.evidence_urls,
            )
        return result

    async def settle_accepted_weight_claim(
        self, dispute: WeightDispute, tenant: Tenant, actor: User
    ) -> Optional[RepriceResult]:
        """
        Settles an ACCEPTED Weight Mismatch claim (injected into
        DelhiveryModulesService.resolve_weight_dispute): re-bills the shipment on the claimed
        weight (declared box sizes kept) through RepricingService, so the refund + CREDIT_NOTE
        equal the over-charge (capped at `dispute.cost_diff_inr` and never debiting the seller,
        A-07) and the bill and COD collectible are restored. The claim row is final and
        row-locked by the caller, so this runs once. No commit.
        """
        if dispute.shipment_id is None:
            return None
        reprice = RepricingService(self.shipment_repo.session)
        await reprice.load_shipment(dispute.shipment_id, tenant.id, for_update=True)
        shipment = await self.shipment_repo.get_shipment_full_details(
            dispute.shipment_id, tenant.id
        )
        if shipment is None or shipment.payment_details is None:
            return None
        manifested_g = float(dispute.manifested_weight_g or 0.0)
        raw_claimed_g = float(dispute.claimed_weight_g or manifested_g)
        claimed_g = max(raw_claimed_g, manifested_g) if manifested_g > 0 else raw_claimed_g
        remark = f"{WEIGHT_DISPUTE_REFUND_REMARK} for {dispute.tracking_id}"
        result = await reprice.apply(
            shipment,
            tenant,
            RepriceChange(
                reason=ChargeAdjustmentReason.CLAIM_ACCEPTED,
                measurement=MeasurementInput(
                    source=MeasurementSource.CLAIM,
                    weight_only_kg=to_money(float(claimed_g) / GRAMS_PER_KG),
                    remark=remark,
                ),
                max_refund=to_money(float(dispute.cost_diff_inr or 0.0)),
                remark=remark,
            ),
            actor,
        )
        self.shipment_repo.session.add(
            ShipmentActivity(
                pickup_id=shipment.id,
                user_id=actor.id,
                activity_type=ActivityType.INFO_UPDATE,
                summary=f"Weight claim accepted: re-billed at {float(claimed_g) / GRAMS_PER_KG:g} kg",
                comment=remark,
                is_public=True,
                diff={**self.weight_audit_diff(result), **result.activity_diff()},
            )
        )
        await self.shipment_repo.session.flush()
        return result

    @staticmethod
    def _measured_dims_label(measurement: MeasurementInput) -> Optional[str]:
        """"L x B x H unit" of the first measured box (None for a weight-only entry)."""
        if not measurement.packages:
            return None
        first = measurement.packages[0]
        unit = getattr(first.dimension_unit, "value", first.dimension_unit)
        return f"{first.length:g} x {first.breadth:g} x {first.height:g} {str(unit).lower()}"

    @staticmethod
    def _measurement_summary(measurement: MeasurementInput, result: RepriceResult) -> str:
        """Activity summary, e.g. "Charged weight 18 kg → 24 kg (4 boxes) at pickup"."""
        old_kg = f"{result.old_chargeable_weight:g}"
        new_kg = f"{result.new_chargeable_weight:g}"
        if measurement.source == MeasurementSource.PICKUP:
            boxes = sum(int(pkg.box_count or 1) for pkg in measurement.packages)
            return PICKUP_MEASUREMENT_REMARK_TEMPLATE.format(old=old_kg, new=new_kg, boxes=boxes)
        return HUB_MEASUREMENT_REMARK_TEMPLATE.format(old=old_kg, new=new_kg)

    @staticmethod
    def weight_audit_diff(result: RepriceResult) -> Dict[str, Any]:
        """Activity diff describing a measurement re-bill."""
        return {
            "chargeable_weight": {
                "old": money_to_float(result.old_chargeable_weight),
                "new": money_to_float(result.new_chargeable_weight),
            },
            "total_logistics_cost": {
                "old": money_to_float(result.old_total),
                "new": money_to_float(result.new_total),
            },
        }

    async def export_shipments_csv(
        self,
        user: User,
        tenant_id: uuid.UUID,
        is_b2b: Optional[bool] = None,
    ) -> io.StringIO:
        items, _ = await self.list_my_shipments(
            user=user,
            tenant_id=tenant_id,
            page=1,
            size=500,
            is_b2b=is_b2b,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Shipment ID",
                "Tracking ID (AWB / LRN)",
                "Order Reference",
                "Status",
                "Service Type",
                "Origin City",
                "Destination City",
                "Chargeable Weight (KG)",
                "Base Freight (INR)",
                "Tax Amount (INR)",
                "Total Logistics Cost (INR)",
                "Created At (UTC)",
            ]
        )
        for s in items:
            pd = s.payment_details
            writer.writerow(
                [
                    str(s.id),
                    s.tracking_id or "",
                    s.order_reference_id or "",
                    s.status.value,
                    s.service_type.value,
                    s.pickup_address.city if s.pickup_address else "",
                    s.delivery_address.city if s.delivery_address else "",
                    f"{(pd.chargeable_weight if pd else 0.0):.2f}",
                    f"{(pd.base_freight if pd else 0.0):.2f}",
                    f"{(pd.tax_amount if pd else 0.0):.2f}",
                    f"{(pd.total_logistics_cost if pd else 0.0):.2f}",
                    s.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )
        output.seek(0)
        return output


# --- Factory for Dependency Injection ---
def get_shipment_service(
    session: AsyncSession = Depends(get_session),
) -> ShipmentService:
    """
    Factory to create ShipmentService with all dependencies.
    """
    repo = ShipmentRepository(session)
    return ShipmentService(repo)

