import logging
import uuid
from typing import List, Optional

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import (
    Address,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
)

# --- Setup Logger ---
logger = logging.getLogger(__name__)


class ShipmentRepository:
    """
    Handles all database interaction for Shipments.
    Follows the "Unit of Work" pattern where complex saves happen in one transaction.
    """

    def __init__(self, session: AsyncSession):
        """
        Dependency Injection: The session is provided by the Service layer.
        """
        self.session = session

    async def get_address_by_id(self, address_id: uuid.UUID) -> Address | None:
        """
        Fetch a single address. Used to validate if a "Saved Address" exists.
        """
        return await self.session.get(Address, address_id)

    async def check_tracking_id_exists(self, tracking_id: str) -> bool:
        """
        Quickly checks if a tracking ID is already taken.
        Returns True if it exists, False if it is available.
        """
        statement = select(PickupRequest).where(
            PickupRequest.tracking_id == tracking_id
        )
        result = await self.session.exec(statement)
        return result.first() is not None

    async def create_shipment_transactional(
        self,
        *,
        pickup: PickupRequest,
        packages: List[PackageDetails],
        documents: List[PickupDocument],
        payment: Optional[PaymentDetails] = None,
        new_pickup_address: Optional[Address] = None,
        new_delivery_address: Optional[Address] = None,
    ) -> PickupRequest:
        """
        The Atomic Transaction.
        Saves the Shipment Header, Addresses (if new), Packages, and Payments
        all at once. If any part fails, the database rolls back automatically.
        """

        logger.info("Repo: Starting Atomic Shipment Transaction")

        # --- Step 1: Handle New Addresses ---
        # If the user typed a new address, we must save it first to get an ID.
        if new_pickup_address:
            self.session.add(new_pickup_address)
            # flush() sends SQL to DB to generate the ID, but doesn't commit yet.
            await self.session.flush()
            await self.session.refresh(new_pickup_address)
            # Link the new ID to the shipment
            pickup.pickup_address_id = new_pickup_address.id
            logger.debug(f"Repo: Created new Pickup Address {new_pickup_address.id}")

        if new_delivery_address:
            self.session.add(new_delivery_address)
            await self.session.flush()
            await self.session.refresh(new_delivery_address)
            pickup.delivery_address_id = new_delivery_address.id
            logger.debug(
                f"Repo: Created new Delivery Address {new_delivery_address.id}"
            )

        # --- Step 2: Save Header ---
        self.session.add(pickup)
        await self.session.flush()  # Generates pickup.id
        await self.session.refresh(pickup)
        logger.debug(f"Repo: Created Pickup Header {pickup.id}")

        # --- Step 3: Save Children ---
        for pkg in packages:
            pkg.pickup_id = pickup.id
            self.session.add(pkg)

        for doc in documents:
            doc.pickup_id = pickup.id
            self.session.add(doc)

        if payment:
            payment.pickup_id = pickup.id
            self.session.add(payment)

        # --- Step 4: Final Commit ---
        await self.session.commit()

        # --- Step 5: Eager Load Relationships (The Fix) ---
        # Instead of simple refresh(), we explicitly load all nested data
        # so Pydantic doesn't crash with "MissingGreenlet"
        logger.debug("Repo: Re-fetching shipment with all relationships")

        query = (
            select(PickupRequest)
            .where(PickupRequest.id == pickup.id)
            .options(
                # We add # type: ignore to silence Pylance for these specific lines
                selectinload(PickupRequest.pickup_address),  # type: ignore
                selectinload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
                selectinload(PickupRequest.documents),  # type: ignore
                selectinload(PickupRequest.payment_details),  # type: ignore
            )
        )

        result = await self.session.exec(query)
        full_pickup = result.one()

        logger.info("Repo: Transaction Committed Successfully")
        return full_pickup
