import random
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.manifests import Manifest, ManifestStatus, ServiceFlow
from app.models.pickups import (
    ActivityType,
    Address,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
)
from app.repositories.shipments import b2b_shipment_clause

IS_B2B_COLUMN_LABEL = "is_b2b"
MEASUREMENT_PENDING_DIFF_KEY = "measurement_pending"
"""Activity-diff marker: a blind LR was picked up without Actual pieces (plan B5)."""


class ManifestRepository:
    """
    DAO for Pickup Requests ('manifests' table) and their linked shipments.
    Every query filters by 'tenant_id' (strict multi-tenant isolation).
    Spring Boot Equivalent: 'interface ManifestRepository extends JpaRepository<Manifest, UUID>'.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _shipment_eager_options() -> tuple:
        """Eager-load options for shipments so async serialization never lazy-loads."""
        return (
            selectinload(PickupRequest.packages),
            joinedload(PickupRequest.payment_details),
            joinedload(PickupRequest.pickup_address),
            joinedload(PickupRequest.delivery_address),
        )

    async def create_manifest(self, manifest: Manifest) -> Manifest:
        self.session.add(manifest)
        await self.session.flush()
        return manifest

    async def get_manifest_by_id(self, manifest_id: uuid.UUID, tenant_id: uuid.UUID) -> Manifest | None:
        query = select(Manifest).where(
            Manifest.id == manifest_id,
            Manifest.tenant_id == tenant_id,
        ).options(
            selectinload(Manifest.pickups).options(*self._shipment_eager_options())
        ).execution_options(populate_existing=True)
        result = await self.session.exec(query)
        return result.first()

    async def lock_manifest(self, manifest_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """
        `SELECT ... FOR UPDATE` on one tenant's manifest row: serialises concurrent status
        changes (dispatch / cancel / not-picked) so a double click acts once (H-4, J55).
        """
        query = (
            select(Manifest.id)
            .where(Manifest.id == manifest_id, Manifest.tenant_id == tenant_id)
            .with_for_update()
        )
        await self.session.exec(query)

    async def pickup_request_number_exists(
        self, tenant_id: uuid.UUID, pickup_request_number: str
    ) -> bool:
        """Returns True when the tenant already uses this 9-digit Pickup ID."""
        query = select(Manifest.id).where(
            Manifest.tenant_id == tenant_id,
            Manifest.pickup_request_number == pickup_request_number,
        )
        result = await self.session.exec(query)
        return result.first() is not None

    async def _release_linked_shipments(
        self,
        manifest: Manifest,
        user_id: Optional[uuid.UUID] = None,
        summary: str = "",
        comment: str = "",
    ) -> None:
        """
        Detaches every linked shipment ('manifest_id = None') and reverts ASSIGNED -> OPEN.
        Logs a ShipmentActivity per shipment when an actor ('user_id') is provided.
        """
        query = select(PickupRequest).where(
            PickupRequest.manifest_id == manifest.id,
            PickupRequest.tenant_id == manifest.tenant_id,
        )
        result = await self.session.exec(query)
        for shipment in result.all():
            old_status = shipment.status
            shipment.manifest_id = None
            if shipment.status == PickupStatus.ASSIGNED:
                shipment.status = PickupStatus.OPEN
            self.session.add(shipment)
            if user_id is not None:
                self.session.add(
                    ShipmentActivity(
                        pickup_id=shipment.id,
                        user_id=user_id,
                        activity_type=ActivityType.STATUS_CHANGE,
                        summary=summary,
                        comment=comment,
                        is_public=False,
                        diff={
                            "status": {
                                "old": old_status.value,
                                "new": shipment.status.value,
                            },
                            "manifest_id": {"old": str(manifest.id), "new": None},
                        },
                    )
                )
        manifest.pickups = []

    async def cancel_manifest(self, manifest: Manifest) -> Manifest:
        manifest.status = ManifestStatus.CANCELED
        self.session.add(manifest)
        await self._release_linked_shipments(manifest)
        await self.session.commit()

        refreshed = await self.get_manifest_by_id(manifest.id, manifest.tenant_id)
        return refreshed or manifest

    async def mark_out_for_pickup(self, manifest: Manifest) -> Manifest:
        """SCHEDULED -> OUT_FOR_PICKUP (status validation happens in the service layer)."""
        manifest.status = ManifestStatus.OUT_FOR_PICKUP
        self.session.add(manifest)
        await self.session.commit()
        refreshed = await self.get_manifest_by_id(manifest.id, manifest.tenant_id)
        return refreshed or manifest

    async def mark_not_picked(
        self, manifest: Manifest, failure_reason: str, user_id: uuid.UUID
    ) -> Manifest:
        """Records a failed pickup attempt and releases linked shipments back to OPEN."""
        manifest.status = ManifestStatus.NOT_PICKED
        manifest.failure_reason = failure_reason
        self.session.add(manifest)
        await self._release_linked_shipments(
            manifest,
            user_id=user_id,
            summary="Pickup Not Picked — Back to Ready to Ship",
            comment=f"Pickup {manifest.pickup_request_number or manifest.id} not picked: {failure_reason}",
        )
        await self.session.commit()
        refreshed = await self.get_manifest_by_id(manifest.id, manifest.tenant_id)
        return refreshed or manifest

    @staticmethod
    def _box_count_for_shipment(shipment: PickupRequest) -> int:
        """Server-computed box count for a single shipment."""
        packaged = sum(max(1, int(p.box_count or 1)) for p in (shipment.packages or []))
        return packaged or (shipment.estimated_box_count or 1)

    async def dispatch_manifest_with_shipments(
        self,
        manifest: Manifest,
        user_id: Optional[uuid.UUID],
        picked_shipment_ids: Optional[List[uuid.UUID]] = None,
        measured_shipment_ids: Optional[Set[uuid.UUID]] = None,
    ) -> List[PickupRequest]:
        """
        Marks the pickup request PICKED, moves the picked LRs to IN_TRANSIT and sends the
        unpicked ones back to Ready to Ship. Does NOT commit: the service re-prices any
        measured LRs in the same transaction, then commits once.

        A blind LR picked without "Actual pieces" gets `measurement_pending` in its
        activity diff (plan B5): it stays billed at the floor until the hub measures it.

        Args:
            manifest: The pickup request being dispatched.
            user_id: Actor recorded on the activities.
            picked_shipment_ids: LRs handed over (None = all linked LRs).
            measured_shipment_ids: LRs whose Actual pieces were recorded at the door.

        Returns:
            The picked shipments, fully loaded, still attached to the session.
        """
        measured = measured_shipment_ids or set()
        manifest.status = ManifestStatus.PICKED
        self.session.add(manifest)

        query = (
            select(PickupRequest)
            .where(
                PickupRequest.manifest_id == manifest.id,
                PickupRequest.tenant_id == manifest.tenant_id,
            )
            .options(*self._shipment_eager_options())
        )
        result = await self.session.exec(query)
        linked_shipments = list(result.unique().all())

        if picked_shipment_ids is None:
            picked_list = linked_shipments
            unpicked_list: List[PickupRequest] = []
        else:
            picked_set = set(picked_shipment_ids)
            picked_list = [s for s in linked_shipments if s.id in picked_set]
            unpicked_list = [s for s in linked_shipments if s.id not in picked_set]

        pur_ref = manifest.pickup_request_number or str(manifest.id)[:8].upper()

        for shipment in picked_list:
            old_status = shipment.status.value
            if shipment.status in (PickupStatus.ASSIGNED, PickupStatus.OPEN, PickupStatus.DRAFT):
                shipment.status = PickupStatus.IN_TRANSIT
            if not shipment.delivery_otp:
                shipment.delivery_otp = str(random.randint(100000, 999999))
            self.session.add(shipment)

            diff: Dict[str, Any] = {
                "status": {"old": old_status, "new": PickupStatus.IN_TRANSIT.value},
                "delivery_otp": {"old": None, "new": shipment.delivery_otp},
            }
            if shipment.is_blind_pickup and shipment.id not in measured:
                diff[MEASUREMENT_PENDING_DIFF_KEY] = True
            activity = ShipmentActivity(
                pickup_id=shipment.id,
                user_id=user_id,
                activity_type=ActivityType.STATUS_CHANGE,
                summary="Dispatched via Pickup Request — In Transit",
                comment=f"Dispatched under Pickup Request {pur_ref}",
                is_public=True,
                diff=diff,
            )
            self.session.add(activity)

        for shipment in unpicked_list:
            old_status = shipment.status.value
            shipment.manifest_id = None
            shipment.status = PickupStatus.OPEN
            self.session.add(shipment)

            unpicked_activity = ShipmentActivity(
                pickup_id=shipment.id,
                user_id=user_id,
                activity_type=ActivityType.STATUS_CHANGE,
                summary="Not Handed Over at Pickup — Back to Ready to Ship",
                comment=f"Detached from Pickup Request {manifest.pickup_request_number or manifest.id} during partial pickup",
                is_public=False,
                diff={
                    "status": {"old": old_status, "new": PickupStatus.OPEN.value},
                    "manifest_id": {"old": str(manifest.id), "new": None},
                },
            )
            self.session.add(unpicked_activity)

        if not manifest.is_blind_pickup and unpicked_list:
            manifest.total_boxes = sum(
                self._box_count_for_shipment(s) for s in picked_list
            )
            self.session.add(manifest)

        await self.session.flush()
        return picked_list

    async def get_shipments_with_flow(
        self, shipment_ids: List[uuid.UUID], tenant_id: uuid.UUID
    ) -> List[Tuple[PickupRequest, bool]]:
        """
        Loads the requested tenant shipments together with their B2B classification
        (computed in SQL by the shared 'b2b_shipment_clause').

        Returns:
            List of (shipment, is_b2b) tuples; ids outside the tenant are simply absent.
        """
        if not shipment_ids:
            return []
        query = (
            select(PickupRequest, b2b_shipment_clause().label(IS_B2B_COLUMN_LABEL))
            .where(
                col(PickupRequest.id).in_(shipment_ids),
                PickupRequest.tenant_id == tenant_id,
            )
            .options(*self._shipment_eager_options())
        )
        result = await self.session.exec(query)
        return [(row[0], bool(row[1])) for row in result.all()]

    async def link_shipments(
        self,
        manifest: Manifest,
        shipments: List[PickupRequest],
        user_id: uuid.UUID,
    ) -> None:
        """Links validated OPEN shipments to the manifest, sets ASSIGNED and logs activity."""
        pur_label = manifest.pickup_request_number or str(manifest.id)[:8].upper()
        for shipment in shipments:
            old_status = shipment.status
            shipment.manifest_id = manifest.id
            shipment.status = PickupStatus.ASSIGNED
            self.session.add(shipment)
            self.session.add(
                ShipmentActivity(
                    pickup_id=shipment.id,
                    user_id=user_id,
                    activity_type=ActivityType.STATUS_CHANGE,
                    summary="Added to Pickup Request — Ready for Pickup",
                    comment=f"Linked to Pickup ID {pur_label}",
                    is_public=False,
                    diff={
                        "status": {
                            "old": old_status.value,
                            "new": PickupStatus.ASSIGNED.value,
                        },
                        "manifest_id": {"old": None, "new": str(manifest.id)},
                    },
                )
            )
        await self.session.flush()

    async def list_manifests(
        self,
        tenant_id: uuid.UUID,
        service_flow: Optional[ServiceFlow] = None,
        status: Optional[ManifestStatus] = None,
        scheduled_date: Optional[date] = None,
    ) -> List[Manifest]:
        query = select(Manifest).where(Manifest.tenant_id == tenant_id)
        if service_flow is not None:
            query = query.where(Manifest.service_flow == service_flow)
        if status is not None:
            query = query.where(Manifest.status == status)
        if scheduled_date is not None:
            query = query.where(Manifest.scheduled_date == scheduled_date)
        query = query.options(
            selectinload(Manifest.pickups).options(selectinload(PickupRequest.packages))
        ).order_by(col(Manifest.scheduled_date).desc())

        result = await self.session.exec(query)
        return list(result.all())

    async def list_scheduled_manifests(
        self,
        tenant_id: uuid.UUID,
        service_flow: ServiceFlow,
        from_date: date,
    ) -> List[Manifest]:
        """SCHEDULED pickups of one flow with 'scheduled_date >= from_date' (add-to-existing candidates)."""
        query = (
            select(Manifest)
            .where(
                Manifest.tenant_id == tenant_id,
                Manifest.service_flow == service_flow,
                Manifest.status == ManifestStatus.SCHEDULED,
                Manifest.scheduled_date >= from_date,
            )
            .options(
                selectinload(Manifest.pickups).options(
                    selectinload(PickupRequest.packages)
                )
            )
            .order_by(col(Manifest.scheduled_date).asc())
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def list_open_unlinked_shipments(
        self,
        tenant_id: uuid.UUID,
        is_b2b: bool,
        pickup_pincode: str,
        created_by_user_id: Optional[uuid.UUID] = None,
    ) -> List[PickupRequest]:
        """
        OPEN, not-yet-manifested shipments of one flow whose pickup snapshot shares the pincode.
        The precise same-location check (snapshot vs saved address) is done in the service.
        """
        flow_clause = b2b_shipment_clause()
        query = (
            select(PickupRequest)
            .join(Address, col(PickupRequest.pickup_address_id) == col(Address.id))
            .where(
                PickupRequest.tenant_id == tenant_id,
                Address.tenant_id == tenant_id,
                PickupRequest.status == PickupStatus.OPEN,
                col(PickupRequest.manifest_id).is_(None),
                Address.pincode == pickup_pincode,
                flow_clause if is_b2b else ~flow_clause,
            )
        )
        if created_by_user_id is not None:
            query = query.where(PickupRequest.created_by_user_id == created_by_user_id)
        query = query.options(*self._shipment_eager_options()).order_by(
            col(PickupRequest.created_at).desc()
        )
        result = await self.session.exec(query)
        return list(result.unique().all())

    async def set_total_boxes(self, manifest: Manifest, total_boxes: int) -> None:
        """Persists the server-computed carton count."""
        manifest.total_boxes = total_boxes
        self.session.add(manifest)
        await self.session.flush()

    async def get_addresses(self, address_ids: List[uuid.UUID], tenant_id: uuid.UUID) -> dict:
        if not address_ids:
            return {}
        query = select(Address).where(
            col(Address.id).in_(address_ids),
            Address.tenant_id == tenant_id
        )
        result = await self.session.exec(query)
        return {a.id: a for a in result.all()}
