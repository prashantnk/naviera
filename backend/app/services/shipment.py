import logging
import random
import string
import uuid
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.pickups import (
    ActivityType,
    Address,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
)
from app.models.tenants import Tenant, User, UserRole
from app.repositories.shipments import ShipmentRepository
from app.schemas.v1.pickups import (
    PickupCreate,
    PickupUpdate,
    PublicActivityRead,
    PublicTrackingRead,
    ShipmentActivityRead,
)

# --- Setup Logger ---
logger = logging.getLogger(__name__)


def generate_tracking_id(prefix: str = "NAV") -> str:
    """
    Generates a unique tracking ID like 'NAV-A1B2C3D4'.
    Collision probability is extremely low for this MVP.
    """
    chars = string.ascii_uppercase + string.digits
    unique_str = "".join(random.choices(chars, k=8))
    return f"{prefix}-{unique_str}"


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
        shipment = await self.shipment_repo.get_shipment_full_details(shipment_id)

        # 2. Basic Existence Check
        if not shipment or shipment.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        # 3. Ownership Check (The Guard Rail)
        # If user is NOT an admin, they MUST be the creator of this shipment.
        if user.role not in [UserRole.admin, UserRole.owner]:
            if shipment.created_by_user_id != user.id:
                # We return 404 instead of 403 to prevent ID enumeration scanning
                raise HTTPException(status_code=404, detail="Shipment not found")

        return shipment

    async def get_timeline(
        self, shipment_id: uuid.UUID, user: User, tenant_id: uuid.UUID
    ) -> List[ShipmentActivityRead]:
        """
        Get Audit Timeline.
        Admins see everything. Customers see only public events for their own shipments.
        """
        # 1. Verify Shipment belongs to tenant
        shipment = await self.shipment_repo.get_shipment_full_details(shipment_id)
        if not shipment or shipment.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        is_admin = user.role in [UserRole.admin, UserRole.owner]

        # 2. Security Check for Customers (Must own the shipment)
        if not is_admin:
            if shipment.created_by_user_id != user.id:
                raise HTTPException(status_code=404, detail="Shipment not found")

        # 3. Fetch History
        activities = await self.shipment_repo.get_shipment_history(shipment_id)

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
            shipment = await self.shipment_repo.get_shipment_full_details(shipment_uuid)
        except ValueError:
            # Fallback to Tracking ID
            shipment = await self.shipment_repo.get_shipment_by_tracking_id(identifier)

        # 🔥 THE SECURITY FIX: Must exist AND belong to the requested tenant!
        if not shipment or shipment.tenant_id != tenant_id:
            logger.warning(
                f"Tracking lookup failed or blocked for identifier: {identifier}"
            )
            raise HTTPException(status_code=404, detail="Shipment not found")

        # Fetch activities to build the public timeline
        activities = await self.shipment_repo.get_shipment_history(shipment.id)

        # Filter: Only show "is_public=True" events
        public_timeline = []
        for a in activities:
            if a.is_public:
                public_timeline.append(
                    PublicActivityRead(
                        timestamp=a.timestamp,
                        status_title=a.summary or "Update",
                        message=a.comment,
                    )
                )

        return PublicTrackingRead(
            tracking_id=shipment.tracking_id,  # type: ignore
            status=shipment.status,
            current_location="Processing",
            estimated_delivery=None,
            timeline=public_timeline,
        )

    async def list_my_shipments(
        self, user: User, tenant_id: uuid.UUID, page: int, size: int
    ) -> Tuple[List[PickupRequest], int]:
        """
        Smart Listing:
        - Admins see ALL shipments for the tenant.
        - Customers see ONLY their own shipments.
        """
        if user.role in [UserRole.admin, UserRole.owner]:
            # Admin View: Pass user_id=None to get everything
            return await self.shipment_repo.list_shipments(
                tenant_id=tenant_id, user_id=None, page=page, size=size
            )
        else:
            # Customer View: Restricted to their ID
            return await self.shipment_repo.list_shipments(
                tenant_id=tenant_id, user_id=user.id, page=page, size=size
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
        self, *, payload: PickupCreate, tenant: Tenant, user_id: uuid.UUID
    ) -> PickupRequest:
        """
        Main entry point for creating a shipment.
        Handles the complexity of "Saved Address" vs "New Address".
        """
        logger.info("Service: Starting shipment creation logic")

        # --- 1. Resolve Pickup Address ---
        # Variable to hold the Address Model (if we are creating a new one)
        new_pickup_addr_model: Optional[Address] = None
        final_pickup_id: uuid.UUID

        if payload.pickup_address_id:
            # Case A: User selected a Saved Address
            logger.debug(
                f"Resolving Saved Pickup Address ID: {payload.pickup_address_id}"
            )
            existing_addr = await self.shipment_repo.get_address_by_id(
                payload.pickup_address_id
            )

            # SECURITY CHECK: Ensure address belongs to this tenant or the address selected is correct
            if not existing_addr or existing_addr.tenant_id != tenant.id:
                logger.warning(
                    f"Security Alert: User tried to access invalid/other tenant address: {payload.pickup_address_id}"
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Pickup Address not found or access denied",
                )
            final_pickup_id = existing_addr.id
        elif payload.new_pickup_address:
            # Case B: User provided a New Address Object
            # Convert Schema -> Model
            logger.debug("Processing New Pickup Address Snapshot")
            # NEW: Generate ID immediately
            final_pickup_id = uuid.uuid4()
            new_pickup_addr_model = Address(
                id=final_pickup_id,  # Assign it here
                **payload.new_pickup_address.model_dump(),
                tenant_id=tenant.id,
                user_id=user_id,
            )

        else:
            # This should be caught by Pydantic validators, but double check
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pickup Address is required",
            )

        # --- 2. Resolve Delivery Address ---
        new_delivery_addr_model: Optional[Address] = None
        final_delivery_id: uuid.UUID

        if payload.delivery_address_id:
            logger.debug(
                f"Resolving Saved Delivery Address ID: {payload.delivery_address_id}"
            )
            existing_del = await self.shipment_repo.get_address_by_id(
                payload.delivery_address_id
            )
            if not existing_del or existing_del.tenant_id != tenant.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Delivery Address not found or access denied",
                )
            final_delivery_id = existing_del.id
        elif payload.new_delivery_address:
            logger.debug("Processing New Delivery Address Snapshot")
            # NEW: Generate ID immediately
            final_delivery_id = uuid.uuid4()
            new_delivery_addr_model = Address(
                id=final_delivery_id,  # Assign it here
                **payload.new_delivery_address.model_dump(),
                tenant_id=tenant.id,
                user_id=user_id,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Delivery Address is required",
            )

        # --- 3. Prepare Child Objects ---
        package_models = [
            PackageDetails(**pkg.model_dump()) for pkg in payload.packages
        ]
        document_models = [
            PickupDocument(**doc.model_dump()) for doc in payload.documents
        ]

        payment_model = None
        if payload.payment_details:
            payment_model = PaymentDetails(**payload.payment_details.model_dump())

        # --- 4. Prepare Shipment Header ---

        new_tracking_id = await self._generate_unique_tracking_id(tenant.slug)
        pickup_request = PickupRequest(
            tenant_id=tenant.id,
            created_by_user_id=user_id,
            order_reference_id=payload.order_reference_id,
            tracking_id=new_tracking_id,
            shipment_type=payload.shipment_type,
            service_type=payload.service_type,
            requested_pickup_date=payload.requested_pickup_date,
            product_category=payload.product_category,
            shipment_description=payload.shipment_description,
            reason_for_return=payload.reason_for_return,
            status=PickupStatus.DRAFT,
            pickup_address_id=final_pickup_id,
            delivery_address_id=final_delivery_id,
        )

        # 5. NEW: Create Initial Activity Log
        initial_activity = ShipmentActivity(
            pickup_id=pickup_request.id,
            user_id=user_id,
            activity_type=ActivityType.INFO_UPDATE,
            summary="Shipment Created",
            comment="Initial Creation",
            is_public=True,
            diff={},  # No diff for creation
        )

        # --- 5. Delegate to Repository ---
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
            "requested_pickup_date",
            "product_category",
            "shipment_description",
            "reason_for_return",
        ]

        for field in fields_to_check:
            new_val = getattr(update_data, field)
            old_val = getattr(old_obj, field)

            # Helper to handle Date comparison vs String comparison
            if new_val is not None and new_val != old_val:
                # Convert dates to ISO string for JSON serialization
                old_json = (
                    old_val.isoformat() if hasattr(old_val, "isoformat") else old_val
                )
                new_json = (
                    new_val.isoformat() if hasattr(new_val, "isoformat") else new_val
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
                    for k in ["weight", "length", "breadth", "height", "description"]:
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

    def _validate_status_transition(
        self, current_status: PickupStatus, new_status: PickupStatus
    ):
        """
        Enforces valid lifecycle moves.
        Draft -> Open -> Assigned -> In Transit -> Completed
        """
        # Allow same status (just updating details)
        if current_status == new_status:
            return

        # Define valid next steps
        valid_transitions = {
            PickupStatus.DRAFT: [PickupStatus.OPEN, PickupStatus.CANCELLED],
            PickupStatus.OPEN: [PickupStatus.ASSIGNED, PickupStatus.CANCELLED],
            PickupStatus.ASSIGNED: [PickupStatus.IN_TRANSIT, PickupStatus.CANCELLED],
            # Removed PickupStatus.EXCEPTION from below lines
            PickupStatus.IN_TRANSIT: [
                PickupStatus.COMPLETED,
                PickupStatus.RTO_INITIATED,
            ],
            PickupStatus.RTO_INITIATED: [PickupStatus.COMPLETED],
            # Terminal states (cannot move out)
            PickupStatus.COMPLETED: [],
            PickupStatus.CANCELLED: [],
        }

        allowed = valid_transitions.get(current_status, [])

        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition: Cannot move from {current_status.value} to {new_status.value}",
            )

    # --- 3. Update Flow (The Main Logic) ---

    async def update_shipment(
        self,
        shipment_id: uuid.UUID,
        payload: PickupUpdate,
        user: User,
        tenant_id: uuid.UUID,
    ) -> PickupRequest:
        """
        Handles Edit Logic:
        1. Permission Check (Admin Only).
        2. Fetch Old Data.
        3. Calculate Diff.
        4. Save Activity Log & Updates.
        """
        # 1. Permission Check
        if user.role not in [UserRole.admin, UserRole.owner]:
            raise HTTPException(
                status_code=403, detail="Only Admins can edit shipments"
            )

        # 2. Fetch Current State
        current = await self.shipment_repo.get_shipment_full_details(shipment_id)
        if not current or current.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Shipment not found")

        # 3. Calculate Diff
        diff = self._calculate_diff(current, payload)

        # --- NEW: Check Status Transition ---
        if payload.status:
            self._validate_status_transition(current.status, payload.status)

        # 4. Handle Address Snapshots (Special Case)
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
            addr = await self.shipment_repo.get_address_by_id(payload.pickup_address_id)
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
                payload.delivery_address_id
            )
            if not addr or addr.tenant_id != tenant_id:
                raise HTTPException(404, "Invalid Delivery Address ID")
            current.delivery_address_id = payload.delivery_address_id
            diff["delivery_address"] = (
                f"Changed to Address ID {payload.delivery_address_id}"
            )

        # 5. Prepare Lists for Sync (Packages)
        packages_to_add = []
        packages_to_delete = []
        if payload.packages is not None:
            old_pkgs_map = {p.id: p for p in current.packages}
            payload_ids = set()

            for pkg_in in payload.packages:
                if pkg_in.id and pkg_in.id in old_pkgs_map:
                    # Update in place
                    payload_ids.add(pkg_in.id)
                    existing = old_pkgs_map[pkg_in.id]
                    for k, v in pkg_in.model_dump(exclude={"id"}).items():
                        setattr(existing, k, v)
                else:
                    # Create new
                    packages_to_add.append(
                        PackageDetails(**pkg_in.model_dump(exclude={"id"}))
                    )

            for old_id, old_pkg in old_pkgs_map.items():
                if old_id not in payload_ids:
                    packages_to_delete.append(old_pkg)

        # 6. Prepare Lists for Sync (Documents)
        documents_to_add = []
        documents_to_delete = []
        if payload.documents is not None:
            old_docs_map = {d.id: d for d in current.documents}
            payload_ids = set()
            for doc_in in payload.documents:
                if doc_in.id and doc_in.id in old_docs_map:
                    payload_ids.add(doc_in.id)
                else:
                    documents_to_add.append(
                        PickupDocument(**doc_in.model_dump(exclude={"id"}))
                    )
            for old_id, old_doc in old_docs_map.items():
                if old_id not in payload_ids:
                    documents_to_delete.append(old_doc)

        # 7. Apply Simple Updates to Header
        if payload.status:
            current.status = payload.status
        if payload.requested_pickup_date:
            current.requested_pickup_date = payload.requested_pickup_date

        # Denormalization: Update latest comment on header if status changed
        if payload.comment and payload.status:
            current.latest_status_comment = payload.comment

        if payload.order_reference_id:
            current.order_reference_id = payload.order_reference_id

        # Sync Financials / Payment Details
        if payload.payment_details:
            if current.payment_details:
                # Update existing payment record
                for k, v in payload.payment_details.model_dump(exclude_unset=True).items():
                    setattr(current.payment_details, k, v)
            else:
                # Create new payment record if it didn't exist
                current.payment_details = PaymentDetails(
                    pickup_id=current.id, 
                    **payload.payment_details.model_dump(exclude_unset=True)
                )
                self.shipment_repo.session.add(current.payment_details)
            diff["payment_details"] = "Updated Financials"

        # 8. Create Activity Log
        activity_type = ActivityType.INFO_UPDATE
        if "status" in diff:
            activity_type = ActivityType.STATUS_CHANGE
        elif not diff and payload.comment:
            activity_type = ActivityType.COMMENT

        # Summary Generator
        summary_list = []
        if "status" in diff and payload.status:
            summary_list.append(f"Status: {payload.status.value}")
        if "packages" in diff:
            summary_list.append("Packages Updated")
        if "documents" in diff:
            summary_list.append("Documents Updated")
        if not summary_list:
            summary_list.append("Details Updated")

        activity = ShipmentActivity(
            pickup_id=shipment_id,
            user_id=user.id,
            activity_type=activity_type,
            summary=", ".join(summary_list),
            comment=payload.comment,
            is_public=payload.is_public,
            diff=diff,
        )

        # 9. Save Everything
        return await self.shipment_repo.update_shipment_with_activity(
            shipment=current,
            activity=activity,
            packages_to_add=packages_to_add,
            packages_to_delete=packages_to_delete,
            documents_to_add=documents_to_add,
            documents_to_delete=documents_to_delete,
            new_pickup_address=new_pickup_addr,
            new_delivery_address=new_delivery_addr,
        )


# --- Factory for Dependency Injection ---
def get_shipment_service(
    session: AsyncSession = Depends(get_session),
) -> ShipmentService:
    """
    Factory to create ShipmentService with all dependencies.
    """
    repo = ShipmentRepository(session)
    return ShipmentService(repo)
