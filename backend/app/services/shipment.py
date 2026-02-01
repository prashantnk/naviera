import logging
import random
import string
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.pickups import (
    Address,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    PickupStatus,
)
from app.models.tenants import Tenant
from app.repositories.shipments import ShipmentRepository
from app.schemas.v1.pickups import PickupCreate

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

        # --- 5. Delegate to Repository ---
        logger.info("Service: Delegating to Repository for Atomic Transaction")
        created_shipment = await self.shipment_repo.create_shipment_transactional(
            pickup=pickup_request,
            packages=package_models,
            documents=document_models,
            payment=payment_model,
            new_pickup_address=new_pickup_addr_model,
            new_delivery_address=new_delivery_addr_model,
        )

        return created_shipment


# --- Factory for Dependency Injection ---
def get_shipment_service(
    session: AsyncSession = Depends(get_session),
) -> ShipmentService:
    """
    Factory to create ShipmentService with all dependencies.
    """
    repo = ShipmentRepository(session)
    return ShipmentService(repo)
