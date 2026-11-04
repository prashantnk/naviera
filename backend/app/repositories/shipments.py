import logging
import uuid
from typing import Any, List, Optional, Tuple

from sqlalchemy import ColumnElement, ScalarSelect, and_, desc, or_
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import (
    Address,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    PickupStatus,
    ProductCategory,
    ServiceOption,
    ShipmentActivity,
    ShipmentType,
)

# --- Setup Logger ---
logger = logging.getLogger(__name__)

B2B_SERVICE_OPTIONS = (ServiceOption.PRIME_SURFACE, ServiceOption.DELHIVERY_B2B_SURFACE)
"""Service options that are B2B cargo by themselves (a B2B booking needs no other marker)."""


def b2b_shipment_clause() -> ColumnElement[bool]:
    """
    Single source of truth (SQL form) for classifying a shipment as B2B cargo.

    A shipment is B2B when ANY of these operational markers is present:
    PO number, blind pickup, carrier's risk (FOV), COMMERCIAL category,
    delivery appointment ID, or a fleet pickup strategy. B2C Reverse (DTO)
    orders with doorstep QC intentionally stay B2C.

    Spring Boot Equivalent: a reusable JPA 'Specification<ShipmentOrder>'.

    Returns:
        A boolean SQL expression usable in WHERE clauses or as a labelled column.
    """
    return or_(
        and_(
            col(PickupRequest.po_number).is_not(None),
            col(PickupRequest.po_number) != "",
        ),
        col(PickupRequest.is_blind_pickup) == True,  # noqa: E712
        col(PickupRequest.is_carriers_risk) == True,  # noqa: E712
        col(PickupRequest.product_category) == ProductCategory.COMMERCIAL,
        col(PickupRequest.appointment_id).is_not(None),
        col(PickupRequest.pickup_strategy).is_not(None),
        col(PickupRequest.service_option).in_(B2B_SERVICE_OPTIONS),
    )


def is_b2b_shipment(shipment: PickupRequest) -> bool:
    """
    In-memory mirror of `b2b_shipment_clause()` for an already loaded shipment.
    Keep both functions in sync: they are the single B2B classification rule.

    Args:
        shipment: The shipment (current, possibly just-edited field values).

    Returns:
        True when any B2B operational marker is present.
    """
    return bool(
        (shipment.po_number is not None and shipment.po_number != "")
        or shipment.is_blind_pickup
        or shipment.is_carriers_risk
        or shipment.product_category == ProductCategory.COMMERCIAL
        or shipment.appointment_id is not None
        or shipment.pickup_strategy is not None
        or getattr(shipment, "service_option", None) in B2B_SERVICE_OPTIONS
    )


ACTIVITY_STATUS_NEW_PATH = ("status", "new")
ACTIVITY_STATUS_OLD_PATH = ("status", "old")
"""JSON paths of the `{"status": {"old", "new"}}` entry every status-change activity writes."""


def held_from_clause() -> ScalarSelect[Any]:
    """
    Correlated scalar subquery: the status a shipment had when it was last moved INTO
    `EXCEPTION`, read from the activity ledger (no extra column needed). Every writer of
    an EXCEPTION status (status update, NDR worker) records `{"status": {"old", "new"}}`.

    Returns:
        A text expression (the raw status value, or NULL when unknown) usable as a
        labelled column next to `PickupRequest`.
    """
    return (
        select(ShipmentActivity.diff[ACTIVITY_STATUS_OLD_PATH].as_string())  # type: ignore[index]
        .where(
            col(ShipmentActivity.pickup_id) == col(PickupRequest.id),
            ShipmentActivity.diff[ACTIVITY_STATUS_NEW_PATH].as_string()  # type: ignore[index]
            == PickupStatus.EXCEPTION.value,
        )
        .order_by(desc(col(ShipmentActivity.timestamp)))
        .limit(1)
        .correlate(PickupRequest)
        .scalar_subquery()
    )


def parse_held_from(raw: Optional[str]) -> Optional[PickupStatus]:
    """
    Maps the raw `held_from_clause()` value onto `PickupStatus`.

    Returns:
        The status, or None for legacy rows / unknown values / a nonsensical EXCEPTION.
    """
    try:
        status = PickupStatus(raw) if raw else None
    except ValueError:
        return None
    return None if status == PickupStatus.EXCEPTION else status


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

    async def get_address_by_id(self, address_id: uuid.UUID, tenant_id: uuid.UUID) -> Address | None:
        """
        Fetch a single address. Used to validate if a "Saved Address" exists.
        """
        query = select(Address).where(Address.id == address_id, Address.tenant_id == tenant_id)
        result = await self.session.exec(query)
        return result.first()

    async def get_held_from_status(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[PickupStatus]:
        """
        The status a tenant's shipment had when its current exception was raised (D-04).

        Returns:
            The pre-exception status, or None when unknown (legacy rows) or not found.
        """
        statement = (
            select(held_from_clause())
            .select_from(PickupRequest)
            .where(
                col(PickupRequest.id) == shipment_id,
                col(PickupRequest.tenant_id) == tenant_id,
            )
        )
        raw = (await self.session.exec(statement)).first()
        return parse_held_from(raw)

    async def check_tracking_id_exists(self, tracking_id: str) -> bool:
        """
        Quickly checks if a tracking ID is already taken.
        Returns True if it exists, False if it is available.
        """
        statement = select(PickupRequest.id).where(
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

        # --- Step 4: Flush session so IDs are available for re-query ---
        await self.session.flush()

        # --- Step 5: Eager Load Relationships (The Fix) ---
        # Instead of simple refresh(), we explicitly load all nested data
        # so Pydantic doesn't crash with "MissingGreenlet"
        logger.debug("Repo: Re-fetching shipment with all relationships")

        query = (
            select(PickupRequest)
            .where(PickupRequest.id == pickup.id)
            .options(
                # We add # type: ignore to silence Pylance for these specific lines
                joinedload(PickupRequest.pickup_address),  # type: ignore
                joinedload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
                selectinload(PickupRequest.documents),  # type: ignore
                joinedload(PickupRequest.payment_details),  # type: ignore
            )
        )

        result = await self.session.exec(query)
        full_pickup = result.one()

        logger.info("Repo: Transaction Flushed Successfully")
        return full_pickup

    async def get_shipment_full_details(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[PickupRequest]:
        """
        Fetches a shipment with ALL relationships loaded.
        Essential for calculating diffs (e.g., comparing old packages vs new packages).
        """
        query = (
            select(PickupRequest)
            .where(PickupRequest.id == shipment_id, PickupRequest.tenant_id == tenant_id)
            .options(
                joinedload(PickupRequest.pickup_address),  # type: ignore
                joinedload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
                selectinload(PickupRequest.documents),  # type: ignore
                joinedload(PickupRequest.payment_details),  # type: ignore
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
            shipment.pickup_address = new_pickup_address

        if new_delivery_address:
            self.session.add(new_delivery_address)
            await self.session.flush()
            shipment.delivery_address_id = new_delivery_address.id
            shipment.delivery_address = new_delivery_address

        # 2. Sync Packages
        for pkg in packages_to_add:
            shipment.packages.append(pkg)

        for pkg in packages_to_delete:
            if pkg in shipment.packages:
                shipment.packages.remove(pkg)
            await self.session.delete(pkg)

        # 3. Sync Documents
        for doc in documents_to_add:
            shipment.documents.append(doc)

        for doc in documents_to_delete:
            if doc in shipment.documents:
                shipment.documents.remove(doc)
            await self.session.delete(doc)

        # 4. Save Shipment Header (Updates existing fields)
        self.session.add(shipment)

        # 5. Save Activity Log
        self.session.add(activity)

        # 6. Flush session so updates are populated in local query. The caller owns the
        # transaction (re-pricing, refunds and RTO billing join it before one commit).
        await self.session.flush()

        # 7. CRITICAL FIX: Eager Load Everything!
        # Do not use simple refresh(). We need to fetch the tree.
        logger.debug("Repo: Re-fetching updated shipment with all relationships")

        query = (
            select(PickupRequest)
            .where(PickupRequest.id == shipment.id)
            .execution_options(populate_existing=True)
            .options(
                joinedload(PickupRequest.pickup_address),  # type: ignore
                joinedload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
                selectinload(PickupRequest.documents),  # type: ignore
                joinedload(PickupRequest.payment_details),  # type: ignore
            )
        )

        result = await self.session.exec(query)
        return result.one()

    # --- NEW: Read & Listing Methods ---

    async def get_shipment_by_tracking_id(
        self, tracking_id: str, tenant_id: uuid.UUID
    ) -> Optional[PickupRequest]:
        """
        Public Tracking: Fetch by human-readable ID (case-insensitive, F-09).
        """
        normalized_id = (tracking_id or "").strip().upper()
        statement = (
            select(PickupRequest)
            .where(
                func.upper(col(PickupRequest.tracking_id)) == normalized_id,
                PickupRequest.tenant_id == tenant_id,
            )
            .options(
                selectinload(PickupRequest.packages),  # type: ignore
                joinedload(PickupRequest.pickup_address),  # type: ignore
                joinedload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.documents),  # type: ignore
                joinedload(PickupRequest.payment_details),  # type: ignore
                selectinload(PickupRequest.activities),  # type: ignore
            )
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_shipment_history(
        self, pickup_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[ShipmentActivity]:
        """
        Fetches the full audit log for a specific shipment, ordered by time.
        """
        statement = (
            select(ShipmentActivity)
            .join(PickupRequest, ShipmentActivity.pickup_id == PickupRequest.id)
            .where(
                ShipmentActivity.pickup_id == pickup_id,
                PickupRequest.tenant_id == tenant_id
            )
            .order_by(desc(col(ShipmentActivity.timestamp)))  # Newest first
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def list_shipments(
        self,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        page: int = 1,
        size: int = 20,
        is_b2b: Optional[bool] = None,
        statuses: Optional[List[PickupStatus]] = None,
        shipment_type: Optional[ShipmentType] = None,
    ) -> Tuple[List[PickupRequest], int]:
        """
        Fetches a paginated list of shipments (optionally only the given `statuses` or `shipment_type`).

        The total comes from a `COUNT(*) OVER()` window on the same query (one
        round trip). Documents are not loaded for lists (`noload` -> []); only
        detail views need them. Packages stay loaded for `total_box_count`.

        Returns: ([List of objects], Total Count)
        """
        filters: List[ColumnElement[bool]] = [col(PickupRequest.tenant_id) == tenant_id]
        if user_id:
            filters.append(col(PickupRequest.created_by_user_id) == user_id)
        if is_b2b is not None:
            b2b_clause = b2b_shipment_clause()
            filters.append(b2b_clause if is_b2b else ~b2b_clause)
        if statuses:
            filters.append(col(PickupRequest.status).in_(list(statuses)))
        if shipment_type is not None:
            filters.append(col(PickupRequest.shipment_type) == shipment_type)

        query = (
            select(PickupRequest, func.count().over().label("total_count"))
            .where(*filters)
            .order_by(desc(PickupRequest.created_at))  # type: ignore
            .offset((page - 1) * size)
            .limit(size)
            .options(
                joinedload(PickupRequest.pickup_address),  # type: ignore
                joinedload(PickupRequest.delivery_address),  # type: ignore
                selectinload(PickupRequest.packages),  # type: ignore
                noload(PickupRequest.documents),  # type: ignore
                joinedload(PickupRequest.payment_details),  # type: ignore
            )
        )
        rows = (await self.session.exec(query)).unique().all()
        if rows:
            return [row[0] for row in rows], int(rows[0][1])

        # Empty page: only an out-of-range page needs a separate count.
        if page == 1:
            return [], 0
        count_query = select(func.count()).select_from(PickupRequest).where(*filters)
        total = (await self.session.exec(count_query)).one()
        return [], int(total)
