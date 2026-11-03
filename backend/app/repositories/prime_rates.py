"""
Data access for the Logismart Prime rate table (`prime_zones`, `prime_zone_pincodes`,
`prime_lanes`, migration M-P2).

Every query filters `tenant_id` (AGENTS §5). Nothing here commits except `commit()`;
the service owns the transaction boundary (dry-run imports roll back).

Spring Boot Equivalent: a '@Repository' over three JPA entities with a couple of
`@Query` joins (zone names for the lanes grid, pincode counts for the zones list).
"""

import uuid
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence

from sqlalchemy import func, update
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.prime import PrimeLane, PrimeLaneMode, PrimeZone, PrimeZonePincode


class PincodeZone(NamedTuple):
    """The zone a pincode belongs to, plus its ODA flag."""

    zone: PrimeZone
    is_oda: bool


class LaneWithZones(NamedTuple):
    """A lane joined with its origin and destination zone names (lanes grid / export)."""

    lane: PrimeLane
    origin_zone_name: str
    dest_zone_name: str


class ZoneWithCount(NamedTuple):
    """A zone with the number of pincodes mapped to it."""

    zone: PrimeZone
    pincode_count: int


class PrimeRatesRepository:
    """Tenant-scoped reads and writes of Prime zones, pincodes and lanes."""

    def __init__(self, session: AsyncSession) -> None:
        """
        Args:
            session: The request (or script) session; the caller owns commit/rollback.
        """
        self.session = session

    # ---- Quote-time reads ------------------------------------------------

    async def get_pincode_zone(self, tenant_id: uuid.UUID, pincode: str) -> Optional[PincodeZone]:
        """
        Resolves a pincode to its zone.

        Args:
            tenant_id: Tenant scope.
            pincode: 6-digit pincode.

        Returns:
            The zone and ODA flag, or None when the pincode is in no zone.
        """
        stmt = (
            select(PrimeZone, PrimeZonePincode.is_oda)
            .join(PrimeZonePincode, col(PrimeZonePincode.zone_id) == col(PrimeZone.id))
            .where(
                PrimeZonePincode.tenant_id == tenant_id,
                PrimeZone.tenant_id == tenant_id,
                PrimeZonePincode.pincode == pincode,
            )
        )
        row = (await self.session.exec(stmt)).first()
        return PincodeZone(zone=row[0], is_oda=bool(row[1])) if row else None

    async def get_active_lane(
        self,
        tenant_id: uuid.UUID,
        origin_zone_id: uuid.UUID,
        dest_zone_id: uuid.UUID,
        mode: PrimeLaneMode,
    ) -> Optional[PrimeLane]:
        """
        The single active lane of a route (partial unique index `uq_prime_lanes_one_active`).

        Args:
            tenant_id: Tenant scope.
            origin_zone_id: Pickup zone.
            dest_zone_id: Delivery zone.
            mode: Transport mode.

        Returns:
            The active lane, or None when the route has no active lane.
        """
        stmt = select(PrimeLane).where(
            PrimeLane.tenant_id == tenant_id,
            PrimeLane.origin_zone_id == origin_zone_id,
            PrimeLane.dest_zone_id == dest_zone_id,
            PrimeLane.mode == mode,
            col(PrimeLane.is_active).is_(True),
        )
        return (await self.session.exec(stmt)).first()

    # ---- Admin reads -----------------------------------------------------

    async def list_zones_with_counts(self, tenant_id: uuid.UUID) -> List[ZoneWithCount]:
        """
        All zones of the tenant with their pincode counts, ordered by name.

        Args:
            tenant_id: Tenant scope.
        """
        count_expr = func.count(col(PrimeZonePincode.id))
        stmt = (
            select(PrimeZone, count_expr)
            .outerjoin(
                PrimeZonePincode,
                (col(PrimeZonePincode.zone_id) == col(PrimeZone.id))
                & (col(PrimeZonePincode.tenant_id) == tenant_id),
            )
            .where(PrimeZone.tenant_id == tenant_id)
            .group_by(col(PrimeZone.id))
            .order_by(col(PrimeZone.name))
        )
        rows = (await self.session.exec(stmt)).all()
        return [ZoneWithCount(zone=row[0], pincode_count=int(row[1])) for row in rows]

    async def list_zones(self, tenant_id: uuid.UUID) -> List[PrimeZone]:
        """
        All zones of the tenant, ordered by name.

        Args:
            tenant_id: Tenant scope.
        """
        stmt = select(PrimeZone).where(PrimeZone.tenant_id == tenant_id).order_by(col(PrimeZone.name))
        return list((await self.session.exec(stmt)).all())

    async def list_lanes(self, tenant_id: uuid.UUID, *, active_only: bool = False) -> List[LaneWithZones]:
        """
        Lanes joined with their zone names, ordered by origin, destination, active first, rate.

        Args:
            tenant_id: Tenant scope.
            active_only: Only the active lane of each route.
        """
        origin = aliased(PrimeZone)
        dest = aliased(PrimeZone)
        stmt = (
            select(PrimeLane, origin.name, dest.name)
            .join(origin, col(PrimeLane.origin_zone_id) == origin.id)
            .join(dest, col(PrimeLane.dest_zone_id) == dest.id)
            .where(
                PrimeLane.tenant_id == tenant_id,
                origin.tenant_id == tenant_id,
                dest.tenant_id == tenant_id,
            )
            .order_by(origin.name, dest.name, col(PrimeLane.is_active).desc(), col(PrimeLane.rate_per_kg))
        )
        if active_only:
            stmt = stmt.where(col(PrimeLane.is_active).is_(True))
        rows = (await self.session.exec(stmt)).all()
        return [LaneWithZones(lane=row[0], origin_zone_name=row[1], dest_zone_name=row[2]) for row in rows]

    async def get_lane(self, tenant_id: uuid.UUID, lane_id: uuid.UUID) -> Optional[PrimeLane]:
        """
        One lane by id, within the tenant.

        Args:
            tenant_id: Tenant scope.
            lane_id: Lane primary key.
        """
        stmt = select(PrimeLane).where(PrimeLane.tenant_id == tenant_id, PrimeLane.id == lane_id)
        return (await self.session.exec(stmt)).first()

    async def get_zone_names(self, tenant_id: uuid.UUID, zone_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, str]:
        """
        Zone id -> name for the given ids, within the tenant.

        Args:
            tenant_id: Tenant scope.
            zone_ids: Zone ids to resolve.
        """
        ids = list(set(zone_ids))
        if not ids:
            return {}
        stmt = select(PrimeZone.id, PrimeZone.name).where(
            PrimeZone.tenant_id == tenant_id, col(PrimeZone.id).in_(ids)
        )
        return {row[0]: row[1] for row in (await self.session.exec(stmt)).all()}

    # ---- Writes ----------------------------------------------------------

    async def deactivate_route(
        self,
        tenant_id: uuid.UUID,
        origin_zone_id: uuid.UUID,
        dest_zone_id: uuid.UUID,
        mode: PrimeLaneMode,
        *,
        except_lane_ids: Sequence[uuid.UUID] = (),
    ) -> int:
        """
        Deactivates every active lane of a route except the given ones (before activating another).

        Args:
            tenant_id: Tenant scope.
            origin_zone_id: Pickup zone.
            dest_zone_id: Delivery zone.
            mode: Transport mode.
            except_lane_ids: Lanes to leave untouched.

        Returns:
            Number of lanes deactivated.
        """
        stmt = (
            update(PrimeLane)
            .where(
                col(PrimeLane.tenant_id) == tenant_id,
                col(PrimeLane.origin_zone_id) == origin_zone_id,
                col(PrimeLane.dest_zone_id) == dest_zone_id,
                col(PrimeLane.mode) == mode,
                col(PrimeLane.is_active).is_(True),
            )
            .values(is_active=False)
            .execution_options(synchronize_session="fetch")
        )
        if except_lane_ids:
            stmt = stmt.where(col(PrimeLane.id).not_in(list(except_lane_ids)))
        result = await self.session.exec(stmt)  # type: ignore[call-overload]
        return int(result.rowcount or 0)

    async def get_zone_by_name(self, tenant_id: uuid.UUID, name: str) -> Optional[PrimeZone]:
        """
        One zone by its exact name, within the tenant.

        Args:
            tenant_id: Tenant scope.
            name: Zone name (unique per tenant).
        """
        stmt = select(PrimeZone).where(PrimeZone.tenant_id == tenant_id, PrimeZone.name == name)
        return (await self.session.exec(stmt)).first()

    async def get_pincode_rows(self, tenant_id: uuid.UUID, pincodes: Iterable[str]) -> Dict[str, PrimeZonePincode]:
        """
        Existing pincode rows for the given pincodes, keyed by pincode.

        Args:
            tenant_id: Tenant scope.
            pincodes: Pincodes to look up.
        """
        pins = list(set(pincodes))
        if not pins:
            return {}
        stmt = select(PrimeZonePincode).where(
            PrimeZonePincode.tenant_id == tenant_id, col(PrimeZonePincode.pincode).in_(pins)
        )
        return {row.pincode: row for row in (await self.session.exec(stmt)).all()}

    def add(self, entity: object) -> None:
        """Stages a new or changed entity whose `tenant_id` the caller already set."""
        self.session.add(entity)

    async def flush(self) -> None:
        """Sends staged changes (so a deactivation lands before the next activation)."""
        await self.session.flush()

    async def commit(self) -> None:
        """Commits the unit of work."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Rolls the unit of work back (dry runs, failed imports)."""
        await self.session.rollback()

    async def refresh(self, entity: object) -> None:
        """Reloads an entity after commit."""
        await self.session.refresh(entity)
