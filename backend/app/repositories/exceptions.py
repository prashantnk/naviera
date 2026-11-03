"""
Data access for the Delivery Exceptions / NDR module.
Spring Boot Equivalent: a '@Repository' with custom JPQL queries.
"""

import uuid
from typing import Any, Dict, Iterable, List, NamedTuple, Optional

from sqlalchemy import ColumnElement, desc, nulls_last, or_
from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import (
    NdrExceptionReason,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
    ShipmentType,
)
from app.repositories.shipments import (
    b2b_shipment_clause,
    held_from_clause,
    parse_held_from,
)
from app.services.ndr_rules import AWAITING_OPS_ACTIONS

MAX_EXCEPTION_SCAN = 2000
"""Safety cap on rows scanned per list request (exceptions are a small subset)."""

NDR_ACTION_DIFF_KEY = "ndr_action"
NDR_RAISE_DIFF_KEY = "ndr_raise"


class ExceptionFacet(NamedTuple):
    """Lightweight projection used for summary counts."""

    ndr_reason: Optional[NdrExceptionReason]
    shipment_type: ShipmentType
    awaiting_ops: bool
    held_from: Optional[PickupStatus] = None


class ExceptionShipment(NamedTuple):
    """A fully loaded on-hold shipment plus derived flags."""

    shipment: PickupRequest
    is_b2b: bool
    awaiting_ops: bool
    held_from: Optional[PickupStatus] = None
    """Status when the current exception was raised (None = unknown / legacy)."""


def _awaiting_ops_clause() -> ColumnElement[bool]:
    """
    Correlated EXISTS: the merchant already answered the CURRENT exception with
    a "wait for ops" action (HOLD / DISPUTE_WEIGHT) recorded in the activity
    ledger after the exception was raised.
    """
    raised_at = col(PickupRequest.exception_raised_at)
    return (
        select(ShipmentActivity.id)
        .where(
            ShipmentActivity.pickup_id == PickupRequest.id,
            ShipmentActivity.diff[NDR_ACTION_DIFF_KEY].as_string().in_(  # type: ignore[index]
                [action.value for action in AWAITING_OPS_ACTIONS]
            ),
            or_(raised_at.is_(None), col(ShipmentActivity.timestamp) >= raised_at),
        )
        .exists()
    )


def _full_load_options() -> List[Any]:
    """Eager-load everything the exception row / action handlers touch (no MissingGreenlet)."""
    return [
        joinedload(PickupRequest.pickup_address),  # type: ignore[arg-type]
        joinedload(PickupRequest.delivery_address),  # type: ignore[arg-type]
        selectinload(PickupRequest.packages),  # type: ignore[arg-type]
        selectinload(PickupRequest.documents),  # type: ignore[arg-type]
        joinedload(PickupRequest.payment_details),  # type: ignore[arg-type]
    ]


class ExceptionsRepository:
    """All SQL for on-hold shipments. Every query is tenant-scoped."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _scope_filters(
        tenant_id: uuid.UUID,
        is_b2b: bool,
        user_id: Optional[uuid.UUID],
    ) -> List[ColumnElement[bool]]:
        """Tenant + EXCEPTION status + flow (+ creator for customers)."""
        b2b_clause = b2b_shipment_clause()
        filters: List[ColumnElement[bool]] = [
            col(PickupRequest.tenant_id) == tenant_id,
            col(PickupRequest.status) == PickupStatus.EXCEPTION,
            b2b_clause if is_b2b else ~b2b_clause,
        ]
        if user_id is not None:
            filters.append(col(PickupRequest.created_by_user_id) == user_id)
        return filters

    async def list_facets(
        self,
        *,
        tenant_id: uuid.UUID,
        is_b2b: bool,
        user_id: Optional[uuid.UUID],
    ) -> List[ExceptionFacet]:
        """Projection (reason, direction, awaiting-ops) of every on-hold shipment in scope."""
        statement = select(
            PickupRequest.ndr_reason,
            PickupRequest.shipment_type,
            _awaiting_ops_clause().label("awaiting_ops"),
            held_from_clause().label("held_from"),
        ).where(*self._scope_filters(tenant_id, is_b2b, user_id))
        rows = (await self.session.exec(statement)).all()
        return [
            ExceptionFacet(row[0], row[1], bool(row[2]), parse_held_from(row[3]))
            for row in rows
        ]

    async def list_exception_shipments(
        self,
        *,
        tenant_id: uuid.UUID,
        is_b2b: bool,
        user_id: Optional[uuid.UUID],
        search: Optional[str],
        reasons: Optional[Iterable[NdrExceptionReason]],
    ) -> List[ExceptionShipment]:
        """
        Fully loaded on-hold shipments in scope, newest exception first.

        Args:
            tenant_id: Tenant isolation key.
            is_b2b: Flow filter via the shared B2B classifier.
            user_id: Restrict to the creator (customers); None for admins.
            search: Case-insensitive match on tracking ID (AWB / LRN) or order ID.
            reasons: Optional reason filter pushed down from a B2B category.
        """
        filters = self._scope_filters(tenant_id, is_b2b, user_id)
        term = (search or "").strip()
        if term:
            filters.append(
                or_(
                    col(PickupRequest.tracking_id).icontains(term, autoescape=True),
                    col(PickupRequest.order_reference_id).icontains(term, autoescape=True),
                )
            )
        if reasons is not None:
            filters.append(col(PickupRequest.ndr_reason).in_(list(reasons)))

        statement = (
            select(
                PickupRequest,
                _awaiting_ops_clause().label("awaiting_ops"),
                held_from_clause().label("held_from"),
            )
            .where(*filters)
            .order_by(
                nulls_last(desc(col(PickupRequest.exception_raised_at))),
                desc(col(PickupRequest.created_at)),
            )
            .limit(MAX_EXCEPTION_SCAN)
            .options(*_full_load_options())
        )
        rows = (await self.session.exec(statement)).unique().all()
        return [
            ExceptionShipment(row[0], is_b2b, bool(row[1]), parse_held_from(row[2]))
            for row in rows
        ]

    async def lock_shipment_row(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> None:
        """
        `SELECT ... FOR UPDATE` on one tenant shipment (no-op if it doesn't exist).

        Serialises concurrent exception actions on the same shipment: a second
        request waits for the first to commit and then re-reads the resolved
        state, so a double-clicked "acknowledge charges" can never debit twice.
        """
        statement = (
            select(PickupRequest.id)
            .where(
                col(PickupRequest.id) == shipment_id,
                col(PickupRequest.tenant_id) == tenant_id,
            )
            .with_for_update()
        )
        await self.session.exec(statement)

    async def get_exception_shipment(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[ExceptionShipment]:
        """One fully loaded shipment (any status) with its flow and awaiting-ops flag."""
        statement = (
            select(
                PickupRequest,
                b2b_shipment_clause().label("is_b2b"),
                _awaiting_ops_clause().label("awaiting_ops"),
                held_from_clause().label("held_from"),
            )
            .where(
                col(PickupRequest.id) == shipment_id,
                col(PickupRequest.tenant_id) == tenant_id,
            )
            .execution_options(populate_existing=True)
            .options(*_full_load_options())
        )
        row = (await self.session.exec(statement)).unique().first()
        if row is None:
            return None
        return ExceptionShipment(row[0], bool(row[1]), bool(row[2]), parse_held_from(row[3]))

    async def get_latest_raise_details(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """The `ndr_raise` payload of the most recent exception raise (e.g. measured weight)."""
        statement = (
            select(ShipmentActivity.diff)
            .join(PickupRequest, col(PickupRequest.id) == col(ShipmentActivity.pickup_id))
            .where(
                ShipmentActivity.pickup_id == shipment_id,
                col(PickupRequest.tenant_id) == tenant_id,
                ShipmentActivity.diff[NDR_RAISE_DIFF_KEY].as_string().is_not(None),  # type: ignore[index]
            )
            .order_by(desc(col(ShipmentActivity.timestamp)))
            .limit(1)
        )
        diff = (await self.session.exec(statement)).first()
        if not isinstance(diff, dict):
            return None
        details = diff.get(NDR_RAISE_DIFF_KEY)
        return details if isinstance(details, dict) else None
