"""
Pure unit tests for WP9 D-09 and WP10 D-03, D-10, D-13, D-17 (no database I/O).
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.manifests import ServiceFlow
from app.models.pickups import Address, AddressCategory, AddressScope, PickupTimeSlot
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.schemas.v1.manifests import ManifestCreate
from app.schemas.v1.pickups import IST_TIMEZONE, AddressUpdate, AppointmentUpdate
from app.services.addresses import AddressService
from app.services.manifests import DEFAULT_CUTOFF, PICKUP_TIMEZONE, ManifestService

# =============================================================================
# D-09 & D-17: AppointmentUpdate validation
# =============================================================================


def test_d09_d17_appointment_update_rejects_naive_datetimes() -> None:
    """Naive datetimes without timezone offset are rejected on AppointmentUpdate."""
    tomorrow = (datetime.now(IST_TIMEZONE) + timedelta(days=1)).date()
    with pytest.raises(ValidationError) as exc_info:
        AppointmentUpdate(
            appointment_start=f"{tomorrow.isoformat()}T10:00:00",
            appointment_end=f"{tomorrow.isoformat()}T14:00:00",
        )
    assert "explicit timezone offset" in str(exc_info.value)


def test_d17_appointment_update_enforces_window_order_past_date_and_po_expiry() -> None:
    """AppointmentUpdate enforces start < end, non-past IST date, and po_expiry_date >= start date."""
    tomorrow_ist = (datetime.now(IST_TIMEZONE) + timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    end_ist = tomorrow_ist + timedelta(hours=4)

    # Valid timezone-aware window + valid PO expiry
    valid = AppointmentUpdate(
        appointment_start=tomorrow_ist.isoformat(),
        appointment_end=end_ist.isoformat(),
        po_number="PO-101, PO-102",
        po_expiry_date=tomorrow_ist.date(),
    )
    assert valid.po_number == "PO-101,PO-102"
    assert valid.appointment_start is not None
    assert valid.appointment_start.tzinfo is not None

    # Reversed window (start >= end)
    with pytest.raises(ValidationError, match="appointment_end must be after appointment_start"):
        AppointmentUpdate(
            appointment_start=end_ist.isoformat(),
            appointment_end=tomorrow_ist.isoformat(),
        )

    # Past date in IST
    yesterday_ist = tomorrow_ist - timedelta(days=2)
    with pytest.raises(ValidationError, match="Appointment date cannot be in the past"):
        AppointmentUpdate(
            appointment_start=yesterday_ist.isoformat(),
            appointment_end=(yesterday_ist + timedelta(hours=2)).isoformat(),
        )

    # PO expiry earlier than appointment date
    with pytest.raises(
        ValidationError, match="po_expiry_date cannot be earlier than the appointment date"
    ):
        AppointmentUpdate(
            appointment_start=tomorrow_ist.isoformat(),
            appointment_end=end_ist.isoformat(),
            po_expiry_date=tomorrow_ist.date() - timedelta(days=1),
        )


# =============================================================================
# D-10 & D-13: ManifestService._adjust_slot and flow/scope rules
# =============================================================================


def test_d10_adjust_slot_rolls_post_cutoff_same_day_to_same_slot_tomorrow() -> None:
    """Past 13:00 IST cutoff rolls same-day requests to the SAME slot tomorrow (not MORNING)."""
    service = ManifestService(session=None)  # type: ignore[arg-type]
    day = date(2026, 11, 2)
    at_cutoff_utc = datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc)  # 13:00 IST
    evening_ist = datetime(2026, 11, 2, 20, 30, tzinfo=PICKUP_TIMEZONE)

    moved_day, moved_slot, adjusted = service._adjust_slot(
        day, PickupTimeSlot.AFTERNOON_14_18.value, DEFAULT_CUTOFF, now=at_cutoff_utc
    )
    assert (moved_day, moved_slot, adjusted) == (
        day + timedelta(days=1),
        PickupTimeSlot.AFTERNOON_14_18.value,
        True,
    )

    moved_day_2, moved_slot_2, adjusted_2 = service._adjust_slot(
        day, PickupTimeSlot.EVENING_18_22.value, DEFAULT_CUTOFF, now=evening_ist
    )
    assert (moved_day_2, moved_slot_2, adjusted_2) == (
        day + timedelta(days=1),
        PickupTimeSlot.EVENING_18_22.value,
        True,
    )


@pytest.mark.asyncio
async def test_d13_b2c_only_customer_cannot_create_b2b_or_blind_pur() -> None:
    """A B2C-only customer is rejected with 403 when attempting to create a B2B or blind PUR."""
    service = ManifestService(session=AsyncMock())
    b2c_user = User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="b2c@example.com",
        supabase_user_id="sub-b2c",
        role=UserRole.customer,
        service_scope=ServiceScope.B2C,
    )
    payload = ManifestCreate(
        pickup_address_id=uuid.uuid4(),
        scheduled_date=date.today(),
        time_slot=PickupTimeSlot.AFTERNOON_14_18.value,
        service_flow=ServiceFlow.B2B,
        is_blind_pickup=True,
        total_boxes=5,
        shipment_ids=[uuid.uuid4()],
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.create_manifest(payload, b2c_user.tenant_id, b2c_user)
    assert exc_info.value.status_code == 403


def test_d13_non_blind_b2b_pur_requires_at_least_one_shipment() -> None:
    """A non-blind B2B PUR with 0 shipments is rejected with 400."""
    service = ManifestService(session=None)  # type: ignore[arg-type]
    payload = ManifestCreate(
        pickup_address_id=uuid.uuid4(),
        scheduled_date=date.today(),
        time_slot=PickupTimeSlot.AFTERNOON_14_18.value,
        service_flow=ServiceFlow.B2B,
        is_blind_pickup=False,
        total_boxes=0,
        shipment_ids=[],
    )
    with pytest.raises(HTTPException) as exc_info:
        service._validate_flow_create_rules(payload)
    assert exc_info.value.status_code == 400
    assert "Select at least one Ready to Ship shipment" in str(exc_info.value.detail)


# =============================================================================
# D-03: AddressService.update_saved_address snapshot protection
# =============================================================================


@pytest.mark.asyncio
async def test_d03_refuses_updating_snapshot_address() -> None:
    """PATCH on an unsaved snapshot address (is_saved=False) is refused with 400."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    snapshot = Address(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        is_saved=False,
        name="Snapshot Receiver",
        phone="9876543210",
        address_line1="12 Snapshot Lane",
        city="Delhi",
        state="DL",
        pincode="110001",
    )
    repo = AsyncMock()
    repo.get_address_by_id = AsyncMock(return_value=snapshot)
    service = AddressService(repo)
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email="u@example.com",
        supabase_user_id="sub-u",
        role=UserRole.customer,
    )
    tenant = Tenant(id=tenant_id, name="T", slug="t")

    with pytest.raises(HTTPException) as exc_info:
        await service.update_saved_address(
            snapshot.id, AddressUpdate(name="Mutated"), user, tenant
        )
    assert exc_info.value.status_code == 400
    assert "Snapshot addresses cannot be modified" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_d03_editing_referenced_saved_address_creates_new_row_and_preserves_old() -> None:
    """Editing a saved address referenced by a shipment retires the old row untouched and inserts a new row."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    old_id = uuid.uuid4()
    original = Address(
        id=old_id,
        tenant_id=tenant_id,
        user_id=user_id,
        is_saved=True,
        category=AddressCategory.WAREHOUSE,
        scope=AddressScope.PRIVATE,
        name="Origin Hub",
        phone="9876543210",
        address_line1="Plot 10, Phase 1",
        city="Bengaluru",
        state="KA",
        pincode="560001",
    )
    persisted: list[Address] = []

    async def _save(addr: Address) -> Address:
        persisted.append(addr)
        return addr

    repo = AsyncMock()
    repo.get_address_by_id = AsyncMock(return_value=original)
    repo.is_address_referenced = AsyncMock(return_value=True)
    repo.create_address = AsyncMock(side_effect=_save)

    service = AddressService(repo)
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email="u@example.com",
        supabase_user_id="sub-u",
        role=UserRole.customer,
    )
    tenant = Tenant(id=tenant_id, name="T", slug="t")

    updated = await service.update_saved_address(
        old_id,
        AddressUpdate(address_line1="Plot 99, New Industrial Area", pincode="560034"),
        user,
        tenant,
    )

    # Original row keeps its original fields for in-transit shipments/labels, with is_saved=False
    assert original.id == old_id
    assert original.is_saved is False
    assert original.address_line1 == "Plot 10, Phase 1"
    assert original.pincode == "560001"

    # Returned row is a brand-new saved Address with the updated fields
    assert updated.id != old_id
    assert updated.is_saved is True
    assert updated.address_line1 == "Plot 99, New Industrial Area"
    assert updated.pincode == "560034"
    assert len(persisted) == 2
