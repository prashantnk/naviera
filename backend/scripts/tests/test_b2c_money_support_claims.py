"""
Pure unit tests (no database) for the B2C money/account journey fixes (b2c-money, 2026-11-01):

- Weight-claim <-> support-ticket correlation is by sub-category: a claim opens its own
  ticket even when another ticket is open on the AWB, and resolving the claim only
  resolves the claim ticket (Delhivery One `weight-dispute`).
- The weight-mismatch list shows the shipment's CURRENT status, without dirtying the row.
- One OPEN ticket per AWB: a second request gets 409 naming the open ticket
  (Delhivery One `support-tickets` "Ticket Already Exists").
- Repository SQL for the sub-category filter and the status lookup.
- Ticket numbers are allocated under a per-tenant advisory lock (no count+1 race) and
  carry the India date.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

from app.models.delhivery_modules import (
    SupportTicket,
    TicketStatus,
    WeightDispute,
    WeightDisputeClaimStatus,
)
from app.models.pickups import PickupStatus
from app.models.tenants import UserRole
from app.repositories.delhivery_modules import (
    DelhiveryModulesRepository,
    ticket_series_lock_key,
)
from app.schemas.v1.delhivery_modules import (
    SupportTicketCreate,
    WeightDisputeResolveRequest,
)
from app.services.delhivery_modules import (
    IN_TRANSIT_STATUS_LABEL,
    WEIGHT_CLAIM_TICKET_SUBCATEGORY,
    DelhiveryModulesService,
)

TENANT_ID = uuid.uuid4()
SELLER_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
AWB = "LOGISMART-TEST-UNIT0001"
NOW = datetime(2026, 11, 1, 9, 0, 0)


def _user(user_id: uuid.UUID, role: UserRole) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role, email=f"{role.value}@example.com")


def _ticket(sub_category: str, status: str = TicketStatus.OPEN.value) -> SupportTicket:
    return SupportTicket(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        user_id=SELLER_ID,
        ticket_number=f"TKT-UNIT-{uuid.uuid4().hex[:4]}",
        tracking_id=AWB,
        category_group="SHIPMENT_ISSUE",
        sub_category=sub_category,
        subject=sub_category,
        description="unit",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _dispute(claim_status: str, shipment_id: Optional[uuid.UUID] = None) -> WeightDispute:
    return WeightDispute(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        merchant_user_id=SELLER_ID,
        shipment_id=shipment_id,
        tracking_id=AWB,
        shipment_status="In-transit",
        manifested_weight_g=1000.0,
        charged_weight_g=3000.0,
        claimed_weight_g=1000.0,
        cost_diff_inr=129.8,
        claim_status=claim_status,
        raised_at=NOW,
        updated_at=NOW,
    )


class _TicketStore:
    """In-memory stand-in for the ticket half of DelhiveryModulesRepository."""

    def __init__(self, tickets: List[SupportTicket]) -> None:
        self.tickets = list(tickets)
        self.messages: List[Any] = []

    async def get_open_tickets_by_tracking_id(
        self, tenant_id: uuid.UUID, tracking_id: str, sub_category: Optional[str] = None
    ) -> List[SupportTicket]:
        return [
            t
            for t in self.tickets
            if t.tenant_id == tenant_id
            and t.tracking_id == tracking_id
            and t.status == TicketStatus.OPEN.value
            and (sub_category is None or t.sub_category == sub_category)
        ]

    async def allocate_ticket_serial(self, _tenant_id: uuid.UUID) -> int:
        return len(self.tickets) + 1

    async def save_ticket(self, ticket: SupportTicket, commit: bool = True) -> SupportTicket:
        if ticket not in self.tickets:
            self.tickets.append(ticket)
        return ticket

    async def save_ticket_message(self, msg: Any, commit: bool = True) -> Any:
        self.messages.append(msg)
        return msg


def _service_with(store: _TicketStore) -> DelhiveryModulesService:
    repo = MagicMock()
    repo.get_open_tickets_by_tracking_id = store.get_open_tickets_by_tracking_id
    repo.allocate_ticket_serial = store.allocate_ticket_serial
    repo.save_ticket = store.save_ticket
    repo.save_ticket_message = store.save_ticket_message
    repo.session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    return DelhiveryModulesService(repo=repo)


@pytest.mark.asyncio
async def test_claim_opens_its_own_ticket_even_when_another_ticket_is_open() -> None:
    """A delivery-query ticket on the AWB must not hide the weight claim from Support."""
    delivery_query = _ticket("Delivery Query")
    store = _TicketStore([delivery_query])
    svc = _service_with(store)

    await svc._open_claim_ticket(_user(SELLER_ID, UserRole.customer), TENANT_ID, _dispute("CLAIM_RAISED"), NOW)

    claim_tickets = [t for t in store.tickets if t.sub_category == WEIGHT_CLAIM_TICKET_SUBCATEGORY]
    assert len(claim_tickets) == 1
    assert claim_tickets[0].user_id == SELLER_ID
    assert claim_tickets[0].status == TicketStatus.OPEN.value


@pytest.mark.asyncio
async def test_claim_does_not_open_a_second_claim_ticket() -> None:
    """An OPEN claim ticket on the AWB is reused (no duplicate)."""
    store = _TicketStore([_ticket(WEIGHT_CLAIM_TICKET_SUBCATEGORY)])
    svc = _service_with(store)

    await svc._open_claim_ticket(_user(SELLER_ID, UserRole.customer), TENANT_ID, _dispute("CLAIM_RAISED"), NOW)

    assert len(store.tickets) == 1


@pytest.mark.asyncio
async def test_resolving_a_claim_resolves_only_the_claim_ticket() -> None:
    """Unrelated open tickets on the same AWB stay OPEN when an admin decides the claim."""
    delivery_query = _ticket("Delivery Query")
    claim_ticket = _ticket(WEIGHT_CLAIM_TICKET_SUBCATEGORY)
    store = _TicketStore([delivery_query, claim_ticket])
    svc = _service_with(store)
    dispute = _dispute(WeightDisputeClaimStatus.CLAIM_RAISED.value)
    svc.repo.get_weight_dispute_by_id = AsyncMock(return_value=dispute)
    svc.repo.save_weight_dispute = AsyncMock(return_value=dispute)

    await svc.resolve_weight_dispute(
        admin_user=_user(ADMIN_ID, UserRole.admin),
        tenant_id=TENANT_ID,
        dispute_id=dispute.id,
        payload=WeightDisputeResolveRequest(
            claim_status=WeightDisputeClaimStatus.REJECTED.value,
            claim_remarks="Scan confirmed 3 kg",
        ),
    )

    assert claim_ticket.status == TicketStatus.RESOLVED.value
    assert delivery_query.status == TicketStatus.OPEN.value
    assert [m.ticket_id for m in store.messages] == [claim_ticket.id]
    assert "REJECTED" in store.messages[0].message


@pytest.mark.parametrize(
    ("shipment_status", "label"),
    [
        (PickupStatus.COMPLETED, "Delivered"),
        (PickupStatus.RTO_IN_TRANSIT, "RTO"),
        (PickupStatus.RTO_DELIVERED, "RTO delivered"),
        (PickupStatus.CANCELLED, "Cancelled"),
        (PickupStatus.LOST, "Lost"),
        (PickupStatus.IN_TRANSIT, IN_TRANSIT_STATUS_LABEL),
        (PickupStatus.OUT_FOR_DELIVERY, IN_TRANSIT_STATUS_LABEL),
        (None, IN_TRANSIT_STATUS_LABEL),
    ],
)
def test_shipment_status_label(shipment_status: Optional[PickupStatus], label: str) -> None:
    assert DelhiveryModulesService._shipment_status_label(shipment_status) == label


@pytest.mark.asyncio
async def test_list_weight_disputes_shows_live_status_without_dirtying_rows() -> None:
    """A parcel audited in transit and delivered later reads "Delivered", and the read stays read-only."""
    shipment_id = uuid.uuid4()
    audited_in_transit = _dispute(WeightDisputeClaimStatus.NONE.value, shipment_id=shipment_id)
    orphan = _dispute(WeightDisputeClaimStatus.NONE.value, shipment_id=None)
    repo = MagicMock()
    repo.list_weight_disputes = AsyncMock(return_value=[audited_in_transit, orphan])
    repo.get_user_emails = AsyncMock(return_value={SELLER_ID: "seller@example.com"})
    repo.get_shipment_statuses = AsyncMock(return_value={shipment_id: PickupStatus.COMPLETED})
    svc = DelhiveryModulesService(repo=repo)

    rows = await svc.list_weight_disputes(user=_user(SELLER_ID, UserRole.customer), tenant_id=TENANT_ID)

    assert rows[0].shipment_status == "Delivered"
    assert rows[1].shipment_status == "In-transit"
    refreshed_history = sa_inspect(rows[0]).attrs.shipment_status.history
    assert not refreshed_history.has_changes(), "the live label must not be flushed back"
    assert refreshed_history.unchanged == ["Delivered"]
    repo.list_weight_disputes.assert_awaited_once()
    assert repo.list_weight_disputes.await_args.kwargs["merchant_user_id"] == SELLER_ID
    repo.get_shipment_statuses.assert_awaited_once_with(TENANT_ID, [shipment_id])


@pytest.mark.asyncio
async def test_list_weight_disputes_skips_status_lookup_without_shipments() -> None:
    repo = MagicMock()
    repo.list_weight_disputes = AsyncMock(return_value=[])
    repo.get_user_emails = AsyncMock(return_value={})
    repo.get_shipment_statuses = AsyncMock()
    svc = DelhiveryModulesService(repo=repo)

    assert await svc.list_weight_disputes(user=_user(SELLER_ID, UserRole.customer), tenant_id=TENANT_ID) == []
    repo.get_shipment_statuses.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_ticket_rejects_second_open_ticket_on_same_awb() -> None:
    """Delhivery One "Ticket Already Exists": 409 that names the open ticket."""
    existing = _ticket(WEIGHT_CLAIM_TICKET_SUBCATEGORY)
    store = _TicketStore([existing])
    svc = _service_with(store)
    shipment = SimpleNamespace(id=uuid.uuid4(), tracking_id=AWB, created_by_user_id=SELLER_ID)
    svc.repo.find_shipment_by_tracking_id = AsyncMock(return_value=shipment)

    with pytest.raises(HTTPException) as exc:
        await svc.create_ticket(
            user=_user(SELLER_ID, UserRole.customer),
            tenant_id=TENANT_ID,
            payload=SupportTicketCreate(
                sub_category="Damage / Missing / Mismatch",
                description="Box arrived crushed",
                tracking_id=AWB,
            ),
        )
    assert exc.value.status_code == 409
    assert existing.ticket_number in exc.value.detail
    assert AWB in exc.value.detail
    assert len(store.tickets) == 1


@pytest.mark.asyncio
async def test_create_ticket_allowed_once_previous_ticket_is_resolved() -> None:
    store = _TicketStore([_ticket("Delivery Query", status=TicketStatus.RESOLVED.value)])
    svc = _service_with(store)
    shipment = SimpleNamespace(id=uuid.uuid4(), tracking_id=AWB, created_by_user_id=SELLER_ID)
    svc.repo.find_shipment_by_tracking_id = AsyncMock(return_value=shipment)

    created = await svc.create_ticket(
        user=_user(SELLER_ID, UserRole.customer),
        tenant_id=TENANT_ID,
        payload=SupportTicketCreate(
            sub_category="Damage / Missing / Mismatch",
            description="Box arrived crushed",
            tracking_id=AWB,
        ),
    )
    assert created.status == TicketStatus.OPEN.value
    assert created.tracking_id == AWB


class _CapturingSession:
    """Captures the compiled SQL of every `exec` and returns canned rows."""

    def __init__(self, rows: List[Any]) -> None:
        self.sql: List[str] = []
        self._rows = rows

    async def exec(self, statement: Any) -> Any:
        self.sql.append(str(statement.compile(dialect=postgresql.dialect())))
        rows = self._rows
        return SimpleNamespace(all=lambda: rows)


@pytest.mark.asyncio
async def test_repo_open_ticket_query_filters_tenant_awb_status_and_optional_sub_category() -> None:
    session = _CapturingSession([])
    repo = DelhiveryModulesRepository(session)  # type: ignore[arg-type]

    await repo.get_open_tickets_by_tracking_id(TENANT_ID, f" {AWB} ")
    await repo.get_open_tickets_by_tracking_id(TENANT_ID, AWB, sub_category=WEIGHT_CLAIM_TICKET_SUBCATEGORY)

    where_clauses = [sql.split("WHERE", 1)[1] for sql in session.sql]
    for where in where_clauses:
        assert "support_tickets.tenant_id" in where
        assert "support_tickets.tracking_id" in where
        assert "support_tickets.status" in where
    assert "support_tickets.sub_category" not in where_clauses[0]
    assert "support_tickets.sub_category" in where_clauses[1]


@pytest.mark.asyncio
async def test_repo_shipment_statuses_is_tenant_scoped_and_skips_empty_input() -> None:
    shipment_id = uuid.uuid4()
    session = _CapturingSession([(shipment_id, PickupStatus.COMPLETED)])
    repo = DelhiveryModulesRepository(session)  # type: ignore[arg-type]

    assert await repo.get_shipment_statuses(TENANT_ID, []) == {}
    assert session.sql == []

    statuses = await repo.get_shipment_statuses(TENANT_ID, [shipment_id, shipment_id])
    assert statuses == {shipment_id: PickupStatus.COMPLETED}
    assert "pickups.tenant_id" in session.sql[0]
    assert "pickups.id IN" in session.sql[0]


@pytest.mark.asyncio
async def test_ticket_number_uses_locked_serial_and_india_date() -> None:
    """22:34 UTC on 30 Oct is 04:04 IST on 31 Oct: the number carries the India date."""
    repo = MagicMock()
    repo.allocate_ticket_serial = AsyncMock(return_value=6)
    svc = DelhiveryModulesService(repo=repo)

    number = await svc._next_ticket_number(TENANT_ID, datetime(2026, 10, 30, 22, 34, 0))

    assert number == "TKT-20261031-0006"
    repo.allocate_ticket_serial.assert_awaited_once_with(TENANT_ID)
    repo.allocate_ticket_serial = AsyncMock(return_value=12345)
    assert await svc._next_ticket_number(TENANT_ID, NOW) == "TKT-20261101-12345"


class _SerialSession:
    """Captures SQL; answers the max-serial query with `current`."""

    def __init__(self, current: Optional[int]) -> None:
        self.sql: List[str] = []
        self.params: List[dict] = []
        self._current = current

    async def exec(self, statement: Any) -> Any:
        compiled = statement.compile(dialect=postgresql.dialect())
        self.sql.append(str(compiled))
        self.params.append(dict(compiled.params))
        current = self._current
        return SimpleNamespace(one=lambda: current)


@pytest.mark.parametrize(("current", "expected"), [(None, 1), (41, 42)])
@pytest.mark.asyncio
async def test_repo_ticket_serial_is_allocated_under_a_tenant_advisory_lock(
    current: Optional[int], expected: int
) -> None:
    session = _SerialSession(current)
    repo = DelhiveryModulesRepository(session)  # type: ignore[arg-type]

    assert await repo.allocate_ticket_serial(TENANT_ID) == expected

    assert "pg_advisory_xact_lock" in session.sql[0]
    assert session.params[0]["lock_key"] == ticket_series_lock_key(TENANT_ID)
    assert ticket_series_lock_key(TENANT_ID) != ticket_series_lock_key(uuid.uuid4())
    assert "split_part(support_tickets.ticket_number" in session.sql[1]
    assert "support_tickets.tenant_id" in session.sql[1]
    assert "~" in session.sql[1]
