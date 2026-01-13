import logging
import uuid
from typing import List, Optional

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
            logger.debug(f"Repo: Created new Delivery Address {new_delivery_address.id}")

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
        await self.session.refresh(pickup)
        
        logger.info("Repo: Transaction Committed Successfully")
        return pickup