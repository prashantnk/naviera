import logging
import uuid
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import (
    Address,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    ShipmentActivity,
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
        activity: ShipmentActivity,
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

        # --- Step 4: Save Initial Activity (NEW) ---
        self.session.add(activity)

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

    async def get_shipment_full_details(
        self, shipment_id: uuid.UUID
    ) -> Optional[PickupRequest]:
        """
        Fetches a shipment with ALL relationships loaded.
        Essential for calculating diffs (e.g., comparing old packages vs new packages).
        """
        query = (
            select(PickupRequest)
            .where(PickupRequest.id == shipment_id)
            .options(
                selectinload(PickupRequest.pickup_address),  # type: ignore
                selectinload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
                selectinload(PickupRequest.documents),  # type: ignore
                selectinload(PickupRequest.payment_details),  # type: ignore
                # We generally don't load 'activities' here to keep it light,
                # unless we need history for some reason.
            )
        )
        result = await self.session.exec(query)
        return result.first()

    async def update_shipment_with_activity(
        self,
        *,
        shipment: PickupRequest,
        activity: ShipmentActivity,
        packages_to_add: List[PackageDetails],
        packages_to_delete: List[PackageDetails],
        documents_to_add: List[PickupDocument],
        documents_to_delete: List[PickupDocument],
        new_pickup_address: Optional[Address] = None,
        new_delivery_address: Optional[Address] = None,
    ) -> PickupRequest:
        """
        The "Edit" Transaction.
        1. Updates Shipment Header.
        2. Syncs Packages & Documents (Add/Remove).
        3. Saves the Activity Log.
        4. RETURNS THE FULLY LOADED OBJECT.
        """
        logger.info(f"Repo: Updating Shipment {shipment.id} with Activity Log")

        # 1. Handle New Addresses (Snapshot Strategy)
        if new_pickup_address:
            self.session.add(new_pickup_address)
            await self.session.flush()
            shipment.pickup_address_id = new_pickup_address.id

        if new_delivery_address:
            self.session.add(new_delivery_address)
            await self.session.flush()
            shipment.delivery_address_id = new_delivery_address.id

        # 2. Sync Packages
        for pkg in packages_to_add:
            pkg.pickup_id = shipment.id
            self.session.add(pkg)

        for pkg in packages_to_delete:
            await self.session.delete(pkg)

        # 3. Sync Documents
        for doc in documents_to_add:
            doc.pickup_id = shipment.id
            self.session.add(doc)

        for doc in documents_to_delete:
            await self.session.delete(doc)

        # 4. Save Shipment Header (Updates existing fields)
        self.session.add(shipment)

        # 5. Save Activity Log
        self.session.add(activity)

        # 6. Commit everything
        await self.session.commit()

        # 7. CRITICAL FIX: Eager Load Everything!
        # Do not use simple refresh(). We need to fetch the tree.
        logger.debug("Repo: Re-fetching updated shipment with all relationships")

        query = (
            select(PickupRequest)
            .where(PickupRequest.id == shipment.id)
            .options(
                selectinload(PickupRequest.pickup_address),  # type: ignore
                selectinload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
                selectinload(PickupRequest.documents),  # type: ignore
                selectinload(PickupRequest.payment_details),  # type: ignore
            )
        )

        result = await self.session.exec(query)
        return result.one()

    # --- NEW: Read & Listing Methods ---

    async def get_shipment_by_tracking_id(
        self, tracking_id: str
    ) -> Optional[PickupRequest]:
        """
        Public Tracking: Fetch by human-readable ID (NAV-XXXX).
        """
        statement = select(PickupRequest).where(
            PickupRequest.tracking_id == tracking_id
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_shipment_history(
        self, pickup_id: uuid.UUID
    ) -> List[ShipmentActivity]:
        """
        Fetches the full audit log for a specific shipment, ordered by time.
        """
        statement = (
            select(ShipmentActivity)
            .where(ShipmentActivity.pickup_id == pickup_id)
            .order_by(desc(col(ShipmentActivity.timestamp)))  # Newest first
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def list_shipments(
        self, tenant_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> List[PickupRequest]:
        """
        The Master List function.
        - If user_id is provided: Returns "My Orders" (Customer view).
        - If user_id is None: Returns "All Orders" (Admin view).
        """
        query = select(PickupRequest).where(PickupRequest.tenant_id == tenant_id)

        if user_id:
            query = query.where(PickupRequest.created_by_user_id == user_id)

        # Order by newest first
        query = query.order_by(desc(col(PickupRequest.created_at)))

        # Optimization: We usually need addresses for the list view
        query = query.options(
            selectinload(PickupRequest.pickup_address),  # type: ignore
            selectinload(PickupRequest.delivery_address),  # type: ignore
            selectinload(PickupRequest.packages),  # type: ignore
            selectinload(PickupRequest.documents),  # type: ignore
            selectinload(PickupRequest.payment_details),  # type: ignore
        )

        result = await self.session.exec(query)
        return list(result.all())
