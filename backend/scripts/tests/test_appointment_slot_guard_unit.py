"""
Pure unit tests for X1: a delivery appointment slot that has already ended is refused.

Both booking paths share `ensure_appointment_slot_not_ended`: the NDR action
`BOOK_APPOINTMENT` (`ExceptionsService._handle_book_appointment`) and
`PATCH /shipments/{id}/appointment` (`ShipmentService.update_appointment`). Otherwise the
temporal-hooks worker would hold the released parcel again on its next run.
No app, no database.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import HTTPException

from app.models.pickups import NdrAction, NdrExceptionReason, PickupStatus, ShipmentType
from app.models.tenants import UserRole
from app.schemas.v1.exceptions import NdrActionRequest
from app.schemas.v1.pickups import AppointmentUpdate
from app.services.exceptions import ExceptionsService, _ActionContext
from app.services.shipment import ShipmentService, ensure_appointment_slot_not_ended

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc)
SLOT = timedelta(hours=4)
ENDED_DETAIL = "This appointment slot has already ended. Pick a slot that ends in the future."


# --- ensure_appointment_slot_not_ended ----------------------------------------------


@pytest.mark.parametrize(
    "end",
    [
        NOW - timedelta(minutes=1),
        NOW,
        (NOW - timedelta(hours=2)).replace(tzinfo=None),  # naive is read as UTC
        (NOW - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=5, minutes=30))),
    ],
)
def test_ended_slot_is_refused(end: datetime) -> None:
    with pytest.raises(HTTPException) as exc:
        ensure_appointment_slot_not_ended(end, NOW)
    assert exc.value.status_code == 400
    assert exc.value.detail == ENDED_DETAIL


@pytest.mark.parametrize(
    "end",
    [
        NOW + timedelta(minutes=1),
        (NOW + timedelta(hours=1)).replace(tzinfo=None),
        (NOW + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=5, minutes=30))),
    ],
)
def test_future_slot_is_accepted(end: datetime) -> None:
    ensure_appointment_slot_not_ended(end, NOW)


def test_defaults_to_the_wall_clock() -> None:
    with pytest.raises(HTTPException):
        ensure_appointment_slot_not_ended(datetime.now(timezone.utc) - timedelta(seconds=1))
    ensure_appointment_slot_not_ended(datetime.now(timezone.utc) + timedelta(hours=1))


# --- NDR action BOOK_APPOINTMENT ----------------------------------------------------


def _held_shipment() -> SimpleNamespace:
    """B2C parcel on an APPOINTMENT_NEEDED hold raised from IN_TRANSIT."""
    return SimpleNamespace(
        appointment_start=None,
        appointment_end=None,
        ndr_reason=NdrExceptionReason.APPOINTMENT_NEEDED,
        shipment_type=ShipmentType.FORWARD,
        manifest_id=None,
    )


def _context(shipment: SimpleNamespace, start: datetime) -> _ActionContext:
    request = NdrActionRequest(
        action=NdrAction.BOOK_APPOINTMENT, appointment_start=start, appointment_end=start + SLOT
    )
    return _ActionContext(
        shipment=shipment,
        request=request,
        actor=None,
        tenant=None,
        is_b2b=False,
        held_from=PickupStatus.IN_TRANSIT,
    )


async def test_book_appointment_refuses_an_ended_slot() -> None:
    shipment = _held_shipment()
    start = datetime.now(timezone.utc) - SLOT - timedelta(hours=1)
    service = ExceptionsService.__new__(ExceptionsService)
    with pytest.raises(HTTPException) as exc:
        await service._handle_book_appointment(_context(shipment, start))
    assert exc.value.status_code == 400
    assert exc.value.detail == ENDED_DETAIL
    assert shipment.appointment_start is None and shipment.appointment_end is None


async def test_book_appointment_refuses_a_slot_that_ended_earlier_today() -> None:
    """Today's date passes the date check; the slot end decides."""
    shipment = _held_shipment()
    start = datetime.now(timezone.utc) - SLOT - timedelta(minutes=5)
    service = ExceptionsService.__new__(ExceptionsService)
    with pytest.raises(HTTPException):
        await service._handle_book_appointment(_context(shipment, start))


async def test_book_appointment_in_progress_slot_is_saved_and_resumes() -> None:
    """A slot that has started but not ended is still bookable."""
    shipment = _held_shipment()
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    service = ExceptionsService.__new__(ExceptionsService)
    outcome = await service._handle_book_appointment(_context(shipment, start))
    assert outcome.new_status == PickupStatus.IN_TRANSIT
    assert shipment.appointment_start == start
    assert shipment.appointment_end == start + SLOT


# --- PATCH /shipments/{id}/appointment ----------------------------------------------


class _FakeShipmentRepo:
    """Returns one shipment; any further repository use fails the test loudly."""

    def __init__(self, shipment: SimpleNamespace):
        self._shipment = shipment

    async def get_shipment_full_details(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[SimpleNamespace]:
        return self._shipment


async def test_update_appointment_refuses_an_ended_slot_before_writing() -> None:
    tenant_id = uuid.uuid4()
    shipment = SimpleNamespace(
        tenant_id=tenant_id,
        created_by_user_id=uuid.uuid4(),
        status=PickupStatus.IN_TRANSIT,
        ndr_reason=None,
        appointment_start=None,
        appointment_end=None,
    )
    start = datetime.now(timezone.utc) - SLOT - timedelta(minutes=5)
    # model_construct skips the IST "date not in the past" validator so the slot can end
    # earlier today regardless of when the test runs.
    payload = AppointmentUpdate.model_construct(appointment_start=start, appointment_end=start + SLOT)
    service = ShipmentService.__new__(ShipmentService)
    service.shipment_repo = _FakeShipmentRepo(shipment)
    staff = SimpleNamespace(id=uuid.uuid4(), role=UserRole.admin)
    with pytest.raises(HTTPException) as exc:
        await service.update_appointment(uuid.uuid4(), payload, staff, tenant_id)
    assert exc.value.status_code == 400
    assert exc.value.detail == ENDED_DETAIL
    assert shipment.appointment_start is None and shipment.appointment_end is None
