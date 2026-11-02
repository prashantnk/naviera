"""
Pure unit tests for Batch 2 backend items:
- B-09: `create_ticket` ignores client `shipment_id` and enforces customer
  ownership on `tracking_id`.
- D-19: `CLOSED` tickets reject customer replies and customer status reopens
  with "reopen by raising a new ticket"; `RESOLVED` tickets auto-reopen on
  customer reply.
- F-02: `DashboardService` computes IST day windows (`UTC+05:30`) and
  `DashboardRepository` shifts naive UTC `ShipmentActivity.timestamp` by
  `INTERVAL '5 hours 30 minutes'` before `date(...)`.
"""

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.models.delhivery_modules import (
    SupportTicket,
    SupportTicketMessage,
    TicketStatus,
)
from app.models.tenants import ServiceScope, User, UserRole
from app.repositories.dashboard import DashboardRepository, ShipmentScope
from app.schemas.v1.delhivery_modules import (
    SupportTicketCreate,
    SupportTicketMessageCreate,
    SupportTicketStatusUpdate,
)
from app.services.dashboard import DashboardService
from app.services.delhivery_modules import DelhiveryModulesService

TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SELLER_A_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SELLER_B_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
STAFF_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SHIPMENT_A_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
FOREIGN_SHIPMENT_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


def _make_user(user_id: uuid.UUID, role: UserRole) -> User:
    return User(
        id=user_id,
        supabase_user_id=f"sub-{user_id}",
        email=f"{role.value}@example.com",
        role=role,
        service_scope=ServiceScope.BOTH,
        is_active=True,
        tenant_id=TENANT_ID,
    )


class _FakeTicketSession:
    async def refresh(self, _obj: Any) -> None:
        return None


class _FakeModulesRepo:
    def __init__(self) -> None:
        self.session = _FakeTicketSession()
        self.shipments: dict[str, Any] = {}
        self.tickets: dict[str, SupportTicket] = {}
        self.messages: dict[uuid.UUID, List[SupportTicketMessage]] = {}

    async def allocate_ticket_serial(self, _tenant_id: uuid.UUID) -> int:
        return len({t.id for t in self.tickets.values()}) + 1

    async def find_shipment_by_tracking_id(
        self, tenant_id: uuid.UUID, tracking_id: str
    ) -> Optional[Any]:
        shipment = self.shipments.get(tracking_id)
        if shipment and shipment.tenant_id == tenant_id:
            return shipment
        return None

    async def save_ticket(
        self, ticket: SupportTicket, commit: bool = True
    ) -> SupportTicket:
        self.tickets[str(ticket.id)] = ticket
        self.tickets[ticket.ticket_number] = ticket
        return ticket

    async def save_ticket_message(
        self, msg: SupportTicketMessage, commit: bool = True
    ) -> SupportTicketMessage:
        self.messages.setdefault(msg.ticket_id, []).append(msg)
        return msg

    async def get_ticket_by_identifier(
        self, tenant_id: uuid.UUID, identifier: str
    ) -> Optional[SupportTicket]:
        ticket = self.tickets.get(identifier)
        if ticket and ticket.tenant_id == tenant_id:
            return ticket
        return None

    async def list_ticket_messages(
        self, ticket_id: uuid.UUID
    ) -> List[SupportTicketMessage]:
        return list(self.messages.get(ticket_id, []))

    async def get_open_tickets_by_tracking_id(
        self,
        tenant_id: uuid.UUID,
        tracking_id: str,
        sub_category: Optional[str] = None,
    ) -> List[SupportTicket]:
        unique = {t.id: t for t in self.tickets.values()}.values()
        return [
            t
            for t in unique
            if t.tenant_id == tenant_id
            and t.tracking_id == tracking_id
            and t.status == TicketStatus.OPEN.value
            and (sub_category is None or t.sub_category == sub_category)
        ]


def _ticket_service(repo: _FakeModulesRepo) -> DelhiveryModulesService:
    service = object.__new__(DelhiveryModulesService)
    service.repo = repo  # type: ignore[assignment]
    return service


@pytest.mark.asyncio
async def test_create_ticket_ignores_client_shipment_id_and_scopes_awb_by_seller() -> None:
    repo = _FakeModulesRepo()
    repo.shipments["AWB-SELLER-A"] = SimpleNamespace(
        id=SHIPMENT_A_ID,
        tenant_id=TENANT_ID,
        tracking_id="AWB-SELLER-A",
        created_by_user_id=SELLER_A_ID,
    )
    service = _ticket_service(repo)
    seller_a = _make_user(SELLER_A_ID, UserRole.customer)
    seller_b = _make_user(SELLER_B_ID, UserRole.customer)

    # 1. Forged `shipment_id` without `tracking_id` is ignored completely (saved as None).
    unlinked = await service.create_ticket(
        user=seller_a,
        tenant_id=TENANT_ID,
        payload=SupportTicketCreate(
            shipment_id=FOREIGN_SHIPMENT_ID,
            sub_category="Pickup Delay",
            description="Forged shipment_id must be ignored",
        ),
    )
    assert unlinked.shipment_id is None

    # 2. Seller A linking their own AWB succeeds and uses the resolved shipment.id
    #    even if a forged `shipment_id` was also supplied.
    linked = await service.create_ticket(
        user=seller_a,
        tenant_id=TENANT_ID,
        payload=SupportTicketCreate(
            shipment_id=FOREIGN_SHIPMENT_ID,
            tracking_id="AWB-SELLER-A",
            sub_category="Pickup Delay",
            description="My own AWB",
        ),
    )
    assert linked.shipment_id == SHIPMENT_A_ID
    assert linked.tracking_id == "AWB-SELLER-A"

    # 3. Seller B attempting to attach Seller A's AWB is rejected with 404.
    with pytest.raises(HTTPException) as exc:
        await service.create_ticket(
            user=seller_b,
            tenant_id=TENANT_ID,
            payload=SupportTicketCreate(
                tracking_id="AWB-SELLER-A",
                sub_category="Pickup Delay",
                description="Trying to attach another seller AWB",
            ),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_closed_ticket_blocks_customer_reply_and_reopen_d19() -> None:
    repo = _FakeModulesRepo()
    service = _ticket_service(repo)
    seller = _make_user(SELLER_A_ID, UserRole.customer)
    support = _make_user(STAFF_ID, UserRole.support_user)

    detail = await service.create_ticket(
        user=seller,
        tenant_id=TENANT_ID,
        payload=SupportTicketCreate(
            sub_category="Delayed Delivery",
            description="Initial issue",
        ),
    )
    ticket_id = str(detail.id)

    # Support marks RESOLVED -> customer reply auto-reopens to OPEN.
    resolved = await service.update_ticket_status(
        user=support,
        tenant_id=TENANT_ID,
        ticket_id=ticket_id,
        payload=SupportTicketStatusUpdate(status=TicketStatus.RESOLVED.value),
    )
    assert resolved.status == TicketStatus.RESOLVED.value

    reopened = await service.add_ticket_message(
        user=seller,
        tenant_id=TENANT_ID,
        ticket_id=ticket_id,
        payload=SupportTicketMessageCreate(message="Still waiting for delivery"),
    )
    assert reopened.status == TicketStatus.OPEN.value

    # Support marks CLOSED -> customer cannot reply or reopen via status endpoint.
    closed = await service.update_ticket_status(
        user=support,
        tenant_id=TENANT_ID,
        ticket_id=ticket_id,
        payload=SupportTicketStatusUpdate(status=TicketStatus.CLOSED.value),
    )
    assert closed.status == TicketStatus.CLOSED.value

    with pytest.raises(HTTPException) as reply_exc:
        await service.add_ticket_message(
            user=seller,
            tenant_id=TENANT_ID,
            ticket_id=ticket_id,
            payload=SupportTicketMessageCreate(message="Can I reopen this?"),
        )
    assert reply_exc.value.status_code == 400
    assert "reopen by raising a new ticket" in reply_exc.value.detail

    with pytest.raises(HTTPException) as status_exc:
        await service.update_ticket_status(
            user=seller,
            tenant_id=TENANT_ID,
            ticket_id=ticket_id,
            payload=SupportTicketStatusUpdate(status=TicketStatus.OPEN.value),
        )
    assert status_exc.value.status_code == 400
    assert "reopen by raising a new ticket" in status_exc.value.detail


def test_dashboard_ist_window_and_sql_offset_f02() -> None:
    # 2026-10-29 20:00 UTC is 2026-10-30 01:30 IST -> IST today is 2026-10-30.
    now_utc = datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)
    window, since_utc = DashboardService._ist_window_and_utc_cutoff(now_utc, days=7)
    assert window[-1] == date(2026, 10, 30)
    assert window[0] == date(2026, 10, 24)
    # 2026-10-24 00:00:00 IST == 2026-10-23 18:30:00 naive UTC
    assert since_utc == datetime(2026, 10, 23, 18, 30, 0)

    # Verify the repository SQL shifts ShipmentActivity.timestamp by +5h30m.
    captured_sql: list[str] = []

    class _CapturingSession:
        async def exec(self, statement: Any) -> Any:
            compiled = str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": False},
                )
            )
            captured_sql.append(compiled)

            class _Result:
                def one(self) -> tuple[None, None, None]:
                    return (None, None, None)

            return _Result()

    import asyncio

    repo = DashboardRepository(_CapturingSession())  # type: ignore[arg-type]
    scope = ShipmentScope(
        tenant_id=TENANT_ID,
        is_b2b=False,
        created_since=since_utc,
        created_by_user_id=None,
    )
    asyncio.run(repo.load_summary_aggregates(scope, []))
    assert len(captured_sql) == 1
    assert "INTERVAL '5 hours 30 minutes'" in captured_sql[0]
