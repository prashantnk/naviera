import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.permissions import (
    assert_can_manage_shipments_or_pickups,
    assert_not_read_only,
    assert_service_scope,
)
from app.models.manifests import Manifest, ManifestStatus, ServiceFlow
from app.models.pickups import (
    ActivityType,
    Address,
    AddressScope,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
    WeightUnit,
)
from app.models.repricing import MeasurementSource
from app.models.tenants import Tenant, User, UserRole
from app.repositories.manifests import ManifestRepository
from app.repositories.shipments import ShipmentRepository
from app.schemas.v1.manifests import ManifestCreate, ManifestDispatchMeasurement
from app.schemas.v1.pickups import PackageCreate
from app.services.repricing import MeasurementInput
from app.services.shipment import ShipmentService

# --- Pickup Request (PUR) number generation ---
PUR_NUMBER_MIN = 100_000_000  # smallest 9-digit number
PUR_NUMBER_MAX = 999_999_999  # largest 9-digit number
PUR_NUMBER_MAX_ATTEMPTS = 10

# --- Pickup slots and cut-off (plan D2) ---
PICKUP_SLOTS: Tuple[str, ...] = ("06:00 - 10:00", "10:00 - 14:00", "14:00 - 18:00", "18:00 - 22:00")
"""The 4 known pickup slots; any requested slot text is normalised to one of them."""
DEFAULT_PICKUP_SLOT = PICKUP_SLOTS[1]
SLOT_HOUR_CHARS = 2
"""Slot text is matched on its first 2 characters (the start hour) when not an exact match."""
DEFAULT_CUTOFF = "13:00"
DEFAULT_CUTOFF_HOUR, DEFAULT_CUTOFF_MINUTE = 13, 0
PICKUP_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
"""The cut-off and slots are Logismart's local (IST) wall-clock times."""
SLOT_ADJUSTED_NOTICE = (
    "Pickup time slot was adjusted because it was past the cut-off time or slot end time."
)

# --- Lifecycle rules ---
ADMIN_ROLES = (UserRole.admin, UserRole.owner, UserRole.operations_user)
CANCELLABLE_STATUSES = (ManifestStatus.SCHEDULED, ManifestStatus.OUT_FOR_PICKUP)
DISPATCHABLE_STATUSES = (ManifestStatus.SCHEDULED, ManifestStatus.OUT_FOR_PICKUP)
NOT_PICKABLE_STATUSES = (ManifestStatus.SCHEDULED, ManifestStatus.OUT_FOR_PICKUP)
PICKED_SHIPMENT_STATUSES = (
    PickupStatus.IN_TRANSIT,
    PickupStatus.OUT_FOR_DELIVERY,
    PickupStatus.EXCEPTION,
    PickupStatus.COMPLETED,
    PickupStatus.RTO_INITIATED,
    PickupStatus.RTO_IN_TRANSIT,
    PickupStatus.RTO_DELIVERED,
    PickupStatus.LOST,
)

# --- Address matching ---
GRAMS_PER_KG = 1000.0
MAX_REFS_IN_ERROR = 5
UNKNOWN_LOCATION_NAME = "Unknown"

ERR_SHIPMENTS_NOT_FOUND = "One or more shipments not found or do not belong to the tenant."
ERR_MIXED_CUSTOMERS = (
    "A pickup request can only contain shipments booked by one customer. "
    "Create a separate pickup request for each customer."
)
ERR_BLIND_PICKUP_NEEDS_LR = (
    "A blind pickup needs at least one LR so the cartons get an AWB, a bill and a label. "
    "Book a blind LR (box count only) for this location first, then select it here."
)
ERR_DISPATCH_WITHOUT_SHIPMENTS = (
    "This pickup request has no shipments (LRs) yet. Add the booked shipments before "
    "confirming the pickup, or mark it Not Picked."
)


class ManifestService:
    """
    Business rules for Pickup Requests (PUR) in both B2C and B2B flows.
    Spring Boot Equivalent: '@Service @Transactional class PickupRequestService'.
    """

    def __init__(self, session: AsyncSession):
        self.repo = ManifestRepository(session)
        self.session = session

    # =====================================================================
    # Pure helpers (no I/O)
    # =====================================================================

    @staticmethod
    def _is_admin(user: Optional[User]) -> bool:
        """True for Admin/Owner (or internal calls without a user)."""
        return user is None or user.role in ADMIN_ROLES

    @staticmethod
    def _is_customer(user: Optional[User]) -> bool:
        """True when the caller is a customer (data must be scoped to their own rows)."""
        return user is not None and user.role == UserRole.customer

    @staticmethod
    def _flow_of(is_b2b: bool) -> ServiceFlow:
        """Maps the shared SQL B2B classifier result to a ServiceFlow."""
        return ServiceFlow.B2B if is_b2b else ServiceFlow.B2C

    @staticmethod
    def _normalize_text(value: Optional[str]) -> str:
        """Lower-cases and strips everything except letters/digits for tolerant comparisons."""
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    @classmethod
    def _is_same_pickup_location(
        cls, shipment_pickup_address: Optional[Address], manifest_address: Optional[Address]
    ) -> bool:
        """
        Pickup addresses are SNAPSHOTTED per shipment, so two different rows can describe the
        same warehouse. They match when they are the same row, OR share pincode + normalized
        address_line1.
        """
        if shipment_pickup_address is None or manifest_address is None:
            return False
        if shipment_pickup_address.id == manifest_address.id:
            return True
        if cls._normalize_text(shipment_pickup_address.pincode) != cls._normalize_text(
            manifest_address.pincode
        ):
            return False
        if cls._normalize_text(shipment_pickup_address.address_line1) != cls._normalize_text(
            manifest_address.address_line1
        ):
            return False
        return True

    @staticmethod
    def _shipment_box_count(shipment: PickupRequest) -> int:
        """Cartons of one shipment: sum of package box counts, else the blind estimate, else 1."""
        packaged = sum((pkg.box_count or 1) for pkg in (shipment.packages or []))
        return packaged or (shipment.estimated_box_count or 1)

    @classmethod
    def _total_boxes(cls, shipments: Iterable[PickupRequest]) -> int:
        """Server-side carton aggregate across linked shipments (zero frontend math)."""
        return sum(cls._shipment_box_count(s) for s in shipments)

    @staticmethod
    def _shipment_weight_kg(shipment: PickupRequest) -> float:
        """Total physical weight in KG across packages (grams converted)."""
        total = 0.0
        for pkg in shipment.packages or []:
            weight = float(pkg.weight or 0.0)
            if pkg.weight_unit == WeightUnit.G:
                weight /= GRAMS_PER_KG
            total += weight * (pkg.box_count or 1)
        return round(total, 2)

    @classmethod
    def _resolve_dispatch_packages(
        cls,
        shipment: Optional[PickupRequest],
        entry: ManifestDispatchMeasurement,
    ) -> Tuple[Optional[Tuple[PackageCreate, ...]], int]:
        """
        Resolves the package lines to measure at pickup handover (A-11).

        - Explicit `entry.packages`: used as-is (full measurement dialog).
        - `entry.actual_pieces` on a blind LR (or LR with no declared package weights):
          returns `(None, actual_pieces)` so the carton count is recorded without inventing
          fake 10 kg boxes (hub measurement remains pending).
        - `entry.actual_pieces` matching the declared piece count: returns `(None, actual_pieces)`
          so multi-line orders (e.g. 2×10 kg + 1×30 kg) are never collapsed or re-billed.
        - `entry.actual_pieces` differing from the declared piece count: scales the declared
          package lines proportionally to the actual piece count.
        """
        if entry.packages:
            total = sum(int(p.box_count or 1) for p in entry.packages)
            return tuple(entry.packages), total

        actual = int(entry.actual_pieces or 1)
        if shipment is None:
            return None, actual
        declared = list(shipment.packages or [])
        has_declared_weights = (
            bool(declared)
            and not shipment.is_blind_pickup
            and any(float(p.weight or 0.0) > 0.0 for p in declared)
        )
        if not has_declared_weights:
            return None, actual

        declared_boxes = sum(int(p.box_count or 1) for p in declared)
        if actual == declared_boxes:
            return None, actual

        if len(declared) == 1:
            pkg = declared[0]
            return (
                (
                    PackageCreate(
                        box_count=actual,
                        length=float(pkg.length),
                        breadth=float(pkg.breadth),
                        height=float(pkg.height),
                        dimension_unit=pkg.dimension_unit,
                        weight=float(pkg.weight),
                        weight_unit=pkg.weight_unit,
                    ),
                ),
                actual,
            )

        total_weight_kg = cls._shipment_weight_kg(shipment)
        per_box_weight_kg = round(total_weight_kg / max(declared_boxes, 1), 3)
        first = declared[0]
        return (
            (
                PackageCreate(
                    box_count=actual,
                    length=max(float(p.length) for p in declared),
                    breadth=max(float(p.breadth) for p in declared),
                    height=max(float(p.height) for p in declared),
                    dimension_unit=first.dimension_unit,
                    weight=max(per_box_weight_kg, 0.01),
                    weight_unit=WeightUnit.KG,
                ),
            ),
            actual,
        )

    @staticmethod
    def _one_line_address(address: Optional[Address]) -> str:
        """'Line 1, Line 2, City, State - 400001' for list rows."""
        if address is None:
            return ""
        parts = [address.address_line1, address.address_line2, address.city, address.state]
        joined = ", ".join(p.strip() for p in parts if p and p.strip())
        return f"{joined} - {address.pincode}" if address.pincode else joined

    @staticmethod
    def _shipment_ref(shipment: PickupRequest) -> str:
        """Human-friendly reference used in error messages."""
        return shipment.tracking_id or shipment.order_reference_id or str(shipment.id)[:8]

    @classmethod
    def _refs(cls, shipments: List[PickupRequest]) -> str:
        """Comma-separated refs, truncated to keep error messages readable."""
        refs = [cls._shipment_ref(s) for s in shipments[:MAX_REFS_IN_ERROR]]
        extra = len(shipments) - len(refs)
        return ", ".join(refs) + (f" (+{extra} more)" if extra > 0 else "")

    @classmethod
    def _to_response(cls, manifest: Manifest, address: Optional[Address]) -> Dict[str, Any]:
        """Serializes a Manifest into the 'ManifestResponse' shape with derived counters."""
        pickups = list(manifest.pickups or [])
        return {
            "id": manifest.id,
            "tenant_id": manifest.tenant_id,
            "pickup_address_id": manifest.pickup_address_id,
            "scheduled_date": manifest.scheduled_date,
            "time_slot": manifest.time_slot,
            "is_blind_pickup": manifest.is_blind_pickup,
            "total_boxes": manifest.total_boxes,
            "status": manifest.status,
            "created_at": getattr(manifest, "created_at", manifest.scheduled_date),
            "service_flow": manifest.service_flow or ServiceFlow.B2B,
            "pickup_request_number": manifest.pickup_request_number,
            "failure_reason": manifest.failure_reason,
            "pickup_location_name": address.name if address is not None else UNKNOWN_LOCATION_NAME,
            "pickup_location_address": cls._one_line_address(address),
            "expected_awbs": len(pickups),
            "picked_awbs": sum(1 for p in pickups if p.status in PICKED_SHIPMENT_STATUSES),
            "shipments": [
                {
                    "id": s.id,
                    "tracking_id": s.tracking_id,
                    "order_reference_id": s.order_reference_id or "",
                    "package_count": cls._shipment_box_count(s),
                    "status": s.status,
                }
                for s in pickups
            ],
        }

    @staticmethod
    def _bad_request(detail: str) -> HTTPException:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    # =====================================================================
    # Access-control helpers
    # =====================================================================

    @classmethod
    def _assert_admin(cls, user: Optional[User], action: str) -> None:
        """Raises 403 unless the caller is an Admin/Owner (and not Read-Only)."""
        assert_not_read_only(user, action)
        if not cls._is_admin(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only Admins can {action}.",
            )

    @classmethod
    def _assert_can_use_pickup_address(cls, address: Address, user: Optional[User]) -> None:
        """Customers may only use their own or tenant-shared pickup addresses."""
        if not cls._is_customer(user):
            return
        if address.user_id != user.id and address.scope != AddressScope.TENANT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to schedule a pickup from another customer's private address.",
            )

    @staticmethod
    def _linked_owner_ids(shipments: Iterable[PickupRequest]) -> Set[Optional[uuid.UUID]]:
        """Distinct `created_by_user_id` values (the booking customers) of shipments."""
        return {s.created_by_user_id for s in shipments}

    @classmethod
    def _customer_owns_manifest(
        cls, manifest: Manifest, address: Optional[Address], user: User
    ) -> bool:
        """
        A customer owns a pickup request only when they booked EVERY linked
        shipment (so run-sheets/labels never expose another customer's
        consignees). Without linked shipments, ownership falls back to the
        pickup address.
        """
        pickups = list(manifest.pickups or [])
        if pickups:
            return cls._linked_owner_ids(pickups) == {user.id}
        return address is not None and address.user_id == user.id

    @classmethod
    def _assert_single_customer(cls, shipments: List[PickupRequest]) -> None:
        """
        Raises 400 when shipments booked by different customers would end up in
        one pickup request (ownership is derived from linked shipments).
        """
        if len(cls._linked_owner_ids(shipments)) > 1:
            raise cls._bad_request(ERR_MIXED_CUSTOMERS)

    @classmethod
    def _assert_can_access_manifest(
        cls, manifest: Manifest, address: Optional[Address], user: Optional[User], action: str
    ) -> None:
        """Raises 403 when a customer touches another customer's pickup request."""
        if cls._is_customer(user) and not cls._customer_owns_manifest(manifest, address, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to {action} another customer's manifest.",
            )

    # =====================================================================
    # Data-loading helpers
    # =====================================================================

    async def _get_address_or_404(self, address_id: uuid.UUID, tenant_id: uuid.UUID) -> Address:
        addresses = await self.repo.get_addresses([address_id], tenant_id)
        if address_id not in addresses:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pickup address not found or does not belong to the tenant.",
            )
        return addresses[address_id]

    async def _get_manifest_for_update(self, manifest_id: uuid.UUID, tenant_id: uuid.UUID) -> Manifest:
        """
        Locks the manifest row, then loads it fresh: concurrent status changes are serialised,
        so the second of two identical clicks sees the new status and is refused (H-4, J55).
        """
        await self.repo.lock_manifest(manifest_id, tenant_id)
        return await self._get_manifest_or_404(manifest_id, tenant_id)

    async def _get_manifest_or_404(self, manifest_id: uuid.UUID, tenant_id: uuid.UUID) -> Manifest:
        manifest = await self.repo.get_manifest_by_id(manifest_id, tenant_id)
        if not manifest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Manifest not found.",
            )
        return manifest

    async def _get_manifest_address(self, manifest: Manifest) -> Optional[Address]:
        addresses = await self.repo.get_addresses([manifest.pickup_address_id], manifest.tenant_id)
        return addresses.get(manifest.pickup_address_id)

    async def _generate_pickup_request_number(self, tenant_id: uuid.UUID) -> str:
        """Random 9-digit Pickup ID, unique per tenant (retries on collision)."""
        for _ in range(PUR_NUMBER_MAX_ATTEMPTS):
            candidate = str(PUR_NUMBER_MIN + secrets.randbelow(PUR_NUMBER_MAX - PUR_NUMBER_MIN + 1))
            if not await self.repo.pickup_request_number_exists(tenant_id, candidate):
                return candidate
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not allocate a unique Pickup ID. Please retry.",
        )

    async def _load_owned_shipments(
        self,
        shipment_ids: List[uuid.UUID],
        tenant_id: uuid.UUID,
        user: Optional[User],
    ) -> List[Tuple[PickupRequest, bool]]:
        """
        Loads (shipment, is_b2b) for every requested id. Raises 400 when any id is missing
        from the tenant or (for customers) belongs to someone else.
        """
        unique_ids = list(dict.fromkeys(shipment_ids))
        rows = await self.repo.get_shipments_with_flow(unique_ids, tenant_id)
        if self._is_customer(user):
            rows = [(s, b2b) for s, b2b in rows if s.created_by_user_id == user.id]
        if len(rows) != len(unique_ids):
            raise self._bad_request(ERR_SHIPMENTS_NOT_FOUND)
        return rows

    def _validate_linkable_shipments(
        self,
        rows: List[Tuple[PickupRequest, bool]],
        service_flow: ServiceFlow,
        pickup_address: Address,
    ) -> List[PickupRequest]:
        """
        Enforces PUR linking rules: OPEN + unlinked, same flow, same pickup location.

        Returns:
            The validated shipments ready to be linked.
        """
        not_open = [s for s, _ in rows if s.status != PickupStatus.OPEN or s.manifest_id is not None]
        if not_open:
            raise self._bad_request(
                "Only OPEN (Ready to Ship) shipments that are not already in a pickup request "
                f"can be added: {self._refs(not_open)}."
            )
        wrong_flow = [s for s, is_b2b in rows if self._flow_of(is_b2b) != service_flow]
        if wrong_flow:
            raise self._bad_request(
                f"{service_flow.value} pickup requests can only include {service_flow.value} "
                f"shipments: {self._refs(wrong_flow)}."
            )
        wrong_location = [
            s for s, _ in rows if not self._is_same_pickup_location(s.pickup_address, pickup_address)
        ]
        if wrong_location:
            raise self._bad_request(
                f"All shipments must be picked up from '{pickup_address.name}': "
                f"{self._refs(wrong_location)}."
            )
        return [s for s, _ in rows]


    @staticmethod
    def _normalise_slot(time_slot: str) -> str:
        """
        Maps free slot text ("14:00-18:00", "14:00 - 18:00", "14") to one of PICKUP_SLOTS,
        matching on the start hour. Unknown text falls back to DEFAULT_PICKUP_SLOT.
        """
        compact = time_slot.replace(" ", "")
        for slot in PICKUP_SLOTS:
            if slot.replace(" ", "") == compact or slot[:SLOT_HOUR_CHARS] == time_slot[:SLOT_HOUR_CHARS]:
                return slot
        return DEFAULT_PICKUP_SLOT

    @staticmethod
    def _parse_cutoff(cutoff_str: str) -> Tuple[int, int]:
        """`HH:MM` tenant cut-off as (hour, minute); a malformed value falls back to 13:00."""
        try:
            hour, minute = (int(part) for part in cutoff_str.split(":"))
        except ValueError:
            return DEFAULT_CUTOFF_HOUR, DEFAULT_CUTOFF_MINUTE
        return hour, minute

    @staticmethod
    def _slot_end_hour(slot: str) -> int:
        """End hour of a normalised slot ("14:00 - 18:00" -> 18)."""
        return int(slot.split("-")[1].strip().split(":")[0])

    def _adjust_slot(
        self, scheduled_date: date, time_slot: str, cutoff_str: str, now: Optional[datetime] = None
    ) -> Tuple[date, str, bool]:
        """
        Plan D2: a late or past pickup slot is moved to the next slot, never rejected.

        The slot text is normalised; a past date becomes today; while the date is today and
        either the tenant cut-off (Logismart's local time, IST) or the slot end has passed,
        the request moves to the next slot (after the last slot: the first slot tomorrow).

        Args:
            scheduled_date: Requested pickup date.
            time_slot: Requested slot text.
            cutoff_str: Tenant cut-off `HH:MM` (IST).
            now: Clock override for tests; defaults to the current IST time.

        Returns:
            (date, normalised slot, whether anything was moved).
        """
        clock = now.astimezone(PICKUP_TIMEZONE) if now else datetime.now(PICKUP_TIMEZONE)
        today = clock.date()
        slot = self._normalise_slot(time_slot)
        adjusted = scheduled_date < today
        scheduled_date = max(scheduled_date, today)
        cutoff_hour, cutoff_minute = self._parse_cutoff(cutoff_str)
        past_cutoff = (clock.hour, clock.minute) >= (cutoff_hour, cutoff_minute)
        if scheduled_date == today and past_cutoff:
            adjusted = True
            scheduled_date = today + timedelta(days=1)
        while scheduled_date == today and clock.hour >= self._slot_end_hour(slot):
            adjusted = True
            next_index = PICKUP_SLOTS.index(slot) + 1
            if next_index >= len(PICKUP_SLOTS):
                next_index = 0
                scheduled_date += timedelta(days=1)
            slot = PICKUP_SLOTS[next_index]
        return scheduled_date, slot, adjusted

    def _validate_flow_create_rules(self, payload: ManifestCreate) -> None:
        """
        Flow rules for a new Pickup Request.

        - B2B blind pickup (D-07): at least one LR must be linked, so every carton collected
          has an AWB, a bill and a label (book a blind LR with only a box count first).
        - B2B non-blind pickup (D-13): at least one Ready to Ship LR must be linked.
        - B2C: no blind pickup; either linked shipments or an expected package count.
        """
        if payload.service_flow != ServiceFlow.B2C:
            if payload.is_blind_pickup and not payload.shipment_ids:
                raise self._bad_request(ERR_BLIND_PICKUP_NEEDS_LR)
            if not payload.shipment_ids:
                raise self._bad_request(
                    "Select at least one Ready to Ship shipment for a B2B pickup request."
                )
            return
        if payload.is_blind_pickup:
            raise self._bad_request("Blind pickups are only available for B2B cargo pickup requests.")
        if not payload.shipment_ids and payload.total_boxes <= 0:
            raise self._bad_request(
                "Select at least one Ready to Ship shipment or enter an expected package count for a B2C pickup request."
            )

    # =====================================================================
    # Use cases
    # =====================================================================

    async def create_manifest(
        self,
        payload: ManifestCreate,
        tenant_id: uuid.UUID,
        current_user: User | None = None,
    ) -> Dict[str, Any]:
        """Creates a SCHEDULED Pickup Request, links validated shipments and assigns a Pickup ID."""
        assert_can_manage_shipments_or_pickups(current_user, "create pickup requests")
        assert_service_scope(
            current_user,
            payload.service_flow == ServiceFlow.B2B or payload.is_blind_pickup,
        )
        pickup_addr = await self._get_address_or_404(payload.pickup_address_id, tenant_id)
        self._assert_can_use_pickup_address(pickup_addr, current_user)
        self._validate_flow_create_rules(payload)

        shipments: List[PickupRequest] = []
        if payload.shipment_ids:
            rows = await self._load_owned_shipments(payload.shipment_ids, tenant_id, current_user)
            shipments = self._validate_linkable_shipments(rows, payload.service_flow, pickup_addr)
            self._assert_single_customer(shipments)

        use_declared_boxes = payload.is_blind_pickup or not shipments
        
        tenant = await self.session.get(Tenant, tenant_id)
        cutoff = DEFAULT_CUTOFF
        if tenant and tenant.settings and tenant.settings.get("operations"):
            cutoff = tenant.settings["operations"].get("pickup_cutoff_time") or DEFAULT_CUTOFF
            
        new_date, new_slot, adjusted = self._adjust_slot(payload.scheduled_date, payload.time_slot, cutoff)
        
        manifest = Manifest(
            tenant_id=tenant_id,
            pickup_address_id=payload.pickup_address_id,
            scheduled_date=new_date,
            time_slot=new_slot,
            service_flow=payload.service_flow,
            pickup_request_number=await self._generate_pickup_request_number(tenant_id),
            is_blind_pickup=payload.is_blind_pickup,
            total_boxes=payload.total_boxes if use_declared_boxes else self._total_boxes(shipments),
            status=ManifestStatus.SCHEDULED,
        )
        manifest = await self.repo.create_manifest(manifest)
        if shipments:
            await self.repo.link_shipments(manifest, shipments, current_user.id if current_user else None)

        await self.session.commit()
        refreshed = await self._get_manifest_or_404(manifest.id, tenant_id)
        resp = self._to_response(refreshed, pickup_addr)
        if adjusted:
            resp["notice"] = SLOT_ADJUSTED_NOTICE
        return resp

    async def list_manifests(
        self,
        tenant_id: uuid.UUID,
        current_user: User | None = None,
        service_flow: Optional[ServiceFlow] = None,
        status_filter: Optional[ManifestStatus] = None,
        scheduled_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Lists pickup requests with optional flow/status/date filters (customer-scoped)."""
        manifests = await self.repo.list_manifests(
            tenant_id,
            service_flow=service_flow,
            status=status_filter,
            scheduled_date=scheduled_date,
        )
        addresses = await self.repo.get_addresses(
            [m.pickup_address_id for m in manifests if m.pickup_address_id], tenant_id
        )
        response = []
        for manifest in manifests:
            address = addresses.get(manifest.pickup_address_id)
            if self._is_customer(current_user) and not self._customer_owns_manifest(
                manifest, address, current_user
            ):
                continue
            response.append(self._to_response(manifest, address))
        return response

    async def list_eligible_shipments(
        self,
        tenant_id: uuid.UUID,
        service_flow: ServiceFlow,
        pickup_address_id: uuid.UUID,
        current_user: User | None = None,
    ) -> List[Dict[str, Any]]:
        """OPEN shipments of one flow that ship from the given pickup location (Create PUR picker)."""
        pickup_addr = await self._get_address_or_404(pickup_address_id, tenant_id)
        self._assert_can_use_pickup_address(pickup_addr, current_user)
        shipments = await self.repo.list_open_unlinked_shipments(
            tenant_id,
            is_b2b=service_flow == ServiceFlow.B2B,
            pickup_pincode=pickup_addr.pincode,
            created_by_user_id=current_user.id if self._is_customer(current_user) else None,
        )
        return [
            {
                "id": s.id,
                "tracking_id": s.tracking_id,
                "order_reference_id": s.order_reference_id,
                "delivery_city": s.delivery_address.city if s.delivery_address else "",
                "delivery_pincode": s.delivery_address.pincode if s.delivery_address else "",
                "package_count": self._shipment_box_count(s),
                "total_weight_kg": self._shipment_weight_kg(s),
                "created_at": s.created_at,
            }
            for s in shipments
            if self._is_same_pickup_location(s.pickup_address, pickup_addr)
        ]

    async def get_pickup_candidates(
        self,
        shipment_ids: List[uuid.UUID],
        tenant_id: uuid.UUID,
        current_user: User | None = None,
    ) -> Dict[str, Any]:
        """
        Validates a Shipments-list selection (one flow, one location, all OPEN) and returns
        today's-or-later SCHEDULED pickups it can be added to.
        """
        if not shipment_ids:
            raise self._bad_request("Select at least one shipment.")
        rows = await self._load_owned_shipments(shipment_ids, tenant_id, current_user)
        flows = {self._flow_of(is_b2b) for _, is_b2b in rows}
        if len(flows) > 1:
            raise self._bad_request(
                "Selected shipments mix B2C and B2B flows. Select shipments from one flow only."
            )
        service_flow = flows.pop()
        anchor_address = rows[0][0].pickup_address
        if anchor_address is None:
            raise self._bad_request("Selected shipments have no pickup address.")
        selected = self._validate_linkable_shipments(rows, service_flow, anchor_address)
        self._assert_single_customer(selected)
        selection_owners = self._linked_owner_ids(selected)

        manifests = await self.repo.list_scheduled_manifests(tenant_id, service_flow, date.today())
        addresses = await self.repo.get_addresses([m.pickup_address_id for m in manifests], tenant_id)
        candidates = []
        for manifest in manifests:
            address = addresses.get(manifest.pickup_address_id)
            if not self._is_same_pickup_location(anchor_address, address):
                continue
            if self._is_customer(current_user) and not self._customer_owns_manifest(
                manifest, address, current_user
            ):
                continue
            if not self._linked_owner_ids(manifest.pickups or []) <= selection_owners:
                continue
            candidates.append(self._to_response(manifest, address))
        return {
            "service_flow": service_flow,
            "pickup_address_id": anchor_address.id,
            "pickup_location_name": anchor_address.name,
            "candidates": candidates,
        }

    async def add_shipments(
        self,
        manifest_id: uuid.UUID,
        shipment_ids: List[uuid.UUID],
        tenant_id: uuid.UUID,
        current_user: User | None = None,
    ) -> Dict[str, Any]:
        """Adds OPEN shipments to an existing SCHEDULED pickup (same flow + location)."""
        assert_can_manage_shipments_or_pickups(
            current_user, "add shipments to pickup requests"
        )
        manifest = await self._get_manifest_for_update(manifest_id, tenant_id)
        address = await self._get_manifest_address(manifest)
        self._assert_can_access_manifest(manifest, address, current_user, "modify")
        if manifest.status != ManifestStatus.SCHEDULED:
            raise self._bad_request(
                f"Shipments can only be added to SCHEDULED pickups (current: {manifest.status.value})."
            )
        if address is None:
            raise self._bad_request("Pickup address of this manifest no longer exists.")

        rows = await self._load_owned_shipments(shipment_ids, tenant_id, current_user)
        shipments = self._validate_linkable_shipments(rows, manifest.service_flow, address)
        self._assert_single_customer(list(manifest.pickups or []) + shipments)
        await self.repo.link_shipments(manifest, shipments, current_user.id if current_user else None)

        refreshed = await self._get_manifest_or_404(manifest.id, tenant_id)
        if not refreshed.is_blind_pickup:
            await self.repo.set_total_boxes(refreshed, self._total_boxes(refreshed.pickups))
        await self.session.commit()
        refreshed = await self._get_manifest_or_404(manifest.id, tenant_id)
        return self._to_response(refreshed, address)

    async def cancel_manifest(
        self,
        manifest_id: uuid.UUID,
        tenant_id: uuid.UUID,
        current_user: User | None = None,
    ) -> Dict[str, Any]:
        assert_can_manage_shipments_or_pickups(current_user, "cancel pickup requests")
        manifest = await self._get_manifest_for_update(manifest_id, tenant_id)
        if manifest.status not in CANCELLABLE_STATUSES:
            raise self._bad_request(f"Cannot cancel manifest in status {manifest.status.value}.")
        address = await self._get_manifest_address(manifest)
        self._assert_can_access_manifest(manifest, address, current_user, "cancel")

        manifest = await self.repo.cancel_manifest(manifest)
        return self._to_response(manifest, address)

    async def mark_out_for_pickup(
        self,
        manifest_id: uuid.UUID,
        tenant_id: uuid.UUID,
        current_user: User | None = None,
    ) -> Dict[str, Any]:
        """Admin-only: SCHEDULED -> OUT_FOR_PICKUP."""
        self._assert_admin(current_user, "mark pickups as out for pickup")
        manifest = await self._get_manifest_for_update(manifest_id, tenant_id)
        if manifest.status != ManifestStatus.SCHEDULED:
            raise self._bad_request(
                f"Only SCHEDULED pickups can go out for pickup (current: {manifest.status.value})."
            )
        manifest = await self.repo.mark_out_for_pickup(manifest)
        return self._to_response(manifest, await self._get_manifest_address(manifest))

    async def mark_not_picked(
        self,
        manifest_id: uuid.UUID,
        failure_reason: str,
        tenant_id: uuid.UUID,
        current_user: User,
    ) -> Dict[str, Any]:
        """Admin-only: SCHEDULED/OUT_FOR_PICKUP -> NOT_PICKED; shipments go back to OPEN."""
        self._assert_admin(current_user, "mark pickups as not picked")
        reason = failure_reason.strip()
        if not reason:
            raise self._bad_request("A failure reason is required.")
        manifest = await self._get_manifest_for_update(manifest_id, tenant_id)
        if manifest.status not in NOT_PICKABLE_STATUSES:
            raise self._bad_request(
                f"Cannot mark a {manifest.status.value} pickup as not picked."
            )
        manifest = await self.repo.mark_not_picked(manifest, reason, current_user.id)
        return self._to_response(manifest, await self._get_manifest_address(manifest))

    async def dispatch_manifest(
        self,
        manifest_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        current_user: User | None = None,
        picked_shipment_ids: Optional[List[uuid.UUID]] = None,
        measurements: Optional[Sequence[ManifestDispatchMeasurement]] = None,
    ) -> Dict[str, Any]:
        self._assert_admin(current_user, "dispatch fleet pickup trucks")
        manifest = await self._get_manifest_for_update(manifest_id, tenant_id)
        if manifest.status not in DISPATCHABLE_STATUSES:
            raise self._bad_request(f"Cannot dispatch manifest in status {manifest.status.value}.")

        pickups = list(manifest.pickups or [])
        if manifest.is_blind_pickup and not pickups:
            # D-07: legacy blind PURs created before the create-time rule have no LR to bill.
            raise self._bad_request(ERR_DISPATCH_WITHOUT_SHIPMENTS)
        if picked_shipment_ids is not None and len(pickups) > 0:
            picked_set = set(picked_shipment_ids)
            if not any(s.id in picked_set for s in pickups):
                raise self._bad_request(
                    "Select at least one shipment to mark as picked up, or mark the pickup request as Not Picked."
                )

        picked_ids = (
            {s.id for s in pickups}
            if picked_shipment_ids is None
            else {s.id for s in pickups if s.id in set(picked_shipment_ids)}
        )
        measurement_list = list(measurements or [])
        for entry in measurement_list:
            if entry.shipment_id not in picked_ids:
                raise self._bad_request(
                    "Cannot record a measurement for a shipment that was not picked up."
                )

        pickup_by_id = {s.id: s for s in pickups}
        resolved_by_id: Dict[uuid.UUID, Tuple[Optional[Tuple[PackageCreate, ...]], int]] = {
            entry.shipment_id: self._resolve_dispatch_packages(
                pickup_by_id.get(entry.shipment_id), entry
            )
            for entry in measurement_list
        }
        effective_user_id = user_id or (current_user.id if current_user else None)
        measured_ids = {
            sid for sid, (pkgs, _) in resolved_by_id.items() if pkgs is not None
        }
        picked_list = await self.repo.dispatch_manifest_with_shipments(
            manifest,
            effective_user_id,
            picked_shipment_ids=picked_shipment_ids,
            measured_shipment_ids=measured_ids,
        )
        if measurement_list:
            tenant = await self.session.get(Tenant, tenant_id)
            if tenant is None:
                raise self._bad_request("Tenant not found.")
            shipment_service = ShipmentService(ShipmentRepository(self.session))
            for entry in measurement_list:
                shipment = await shipment_service.shipment_repo.get_shipment_full_details(
                    entry.shipment_id, tenant_id
                )
                if shipment is None:
                    raise self._bad_request(ERR_SHIPMENTS_NOT_FOUND)
                resolved_pkgs, box_count = self._resolve_dispatch_packages(shipment, entry)
                resolved_by_id[entry.shipment_id] = (resolved_pkgs, box_count)
                if resolved_pkgs is None:
                    if shipment.is_blind_pickup or not shipment.packages:
                        old_boxes = shipment.estimated_box_count
                        shipment.estimated_box_count = box_count
                        self.session.add(shipment)
                        self.session.add(
                            ShipmentActivity(
                                pickup_id=shipment.id,
                                user_id=effective_user_id,
                                activity_type=ActivityType.INFO_UPDATE,
                                summary=(
                                    f"Pickup handover: {box_count} actual piece(s) recorded "
                                    "(hub measurement pending)"
                                ),
                                comment=entry.remark
                                or f"{box_count} piece(s) handed over at pickup; hub measurement pending.",
                                is_public=True,
                                diff={
                                    "estimated_box_count": {"old": old_boxes, "new": box_count},
                                    "measurement_pending": True,
                                },
                            )
                        )
                    continue
                measurement_in = MeasurementInput(
                    source=MeasurementSource.PICKUP,
                    packages=resolved_pkgs,
                    evidence_urls=tuple(entry.evidence_urls or []),
                    remark=entry.remark,
                )
                result = await shipment_service.measure_no_commit(
                    shipment, tenant, measurement_in, current_user
                )
                self.session.add(
                    ShipmentActivity(
                        pickup_id=shipment.id,
                        user_id=effective_user_id,
                        activity_type=ActivityType.INFO_UPDATE,
                        summary=shipment_service._measurement_summary(measurement_in, result),
                        comment=entry.remark or shipment_service._measurement_summary(measurement_in, result),
                        is_public=True,
                        diff={
                            **shipment_service.weight_audit_diff(result),
                            **result.activity_diff(),
                        },
                    )
                )
            measured_boxes = {
                sid: box_count for sid, (_, box_count) in resolved_by_id.items()
            }
            manifest.total_boxes = sum(
                measured_boxes.get(s.id, self._shipment_box_count(s)) for s in picked_list
            )
            self.session.add(manifest)

        await self.session.commit()
        manifest = await self._get_manifest_or_404(manifest_id, tenant_id)
        return self._to_response(manifest, await self._get_manifest_address(manifest))

    async def get_manifest_with_details(
        self,
        manifest_id: uuid.UUID,
        tenant_id: uuid.UUID,
        current_user: User | None = None,
    ) -> Tuple[Manifest, Optional[Address], List[PickupRequest]]:
        """Manifest + pickup address + linked shipments for PDFs (customer-scoped)."""
        manifest = await self._get_manifest_or_404(manifest_id, tenant_id)
        pickup_addr = await self._get_manifest_address(manifest)
        self._assert_can_access_manifest(manifest, pickup_addr, current_user, "view")
        return manifest, pickup_addr, list(manifest.pickups or [])

    async def get_shipments_for_labels(
        self,
        manifest_id: uuid.UUID,
        tenant_id: uuid.UUID,
        current_user: User | None = None,
    ) -> Tuple[Manifest, List[PickupRequest]]:
        """Linked shipments whose labels must be printed before pickup (400 when none)."""
        manifest, _, shipments = await self.get_manifest_with_details(
            manifest_id, tenant_id, current_user
        )
        if not shipments:
            raise self._bad_request("This pickup request has no linked shipments to print labels for.")
        return manifest, shipments
