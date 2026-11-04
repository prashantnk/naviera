"""
Pure unit tests (no DB) for the read-only ops fields on `PickupRead` (WP2 / E-06 / E-11).

- `door_collectible` must come from `services.cod_payout.door_collectible` (never the FE).
- `allowed_next_statuses` must mirror `ShipmentLifecycleMachine` exactly.
"""

import uuid
from datetime import date, datetime, time, timezone

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.shipments import _serialize_shipment, _serialize_shipment_list
from app.models.manifests import Manifest, ManifestStatus
from app.models.pickups import (
    ActivityType,
    Address,
    PackageDetails,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ProductCategory,
    ServiceOption,
    ServiceType,
    ShipmentActivity,
    ShipmentType,
)
from app.models.tenants import User, UserRole
from app.repositories.manifests import ManifestRepository
from app.repositories.shipments import ShipmentRepository
from app.schemas.v1.pickups import (
    PaymentDetailsRead,
    PickupRead,
    PublicTrackingRead,
    ShipmentActivityRead,
)
from app.services.shipment import ShipmentService
from app.services.shipment_lifecycle import ShipmentLifecycleMachine

COD_GOODS = 4999.0
TO_PAY_FREIGHT_DUE = 120.5


def _pickup_with_payment(payment: PaymentDetailsRead | None) -> PickupRead:
    """A PickupRead carrying only what the computed fields read."""
    return PickupRead.model_construct(status=PickupStatus.IN_TRANSIT, payment_details=payment)


def _payment(is_cod: bool, cod_amount: float, freight_collectible: float = 0.0) -> PaymentDetailsRead:
    return PaymentDetailsRead.model_construct(
        is_cod=is_cod, cod_amount=cod_amount, freight_collectible=freight_collectible
    )


def test_door_collectible_cod_shipment_returns_cod_amount() -> None:
    assert _pickup_with_payment(_payment(True, COD_GOODS)).door_collectible == COD_GOODS


def test_door_collectible_prepaid_is_zero_even_with_stale_cod_amount() -> None:
    assert _pickup_with_payment(_payment(False, COD_GOODS)).door_collectible == 0.0


def test_door_collectible_adds_freight_still_due() -> None:
    pickup = _pickup_with_payment(_payment(True, COD_GOODS, TO_PAY_FREIGHT_DUE))
    assert pickup.door_collectible == pytest.approx(COD_GOODS + TO_PAY_FREIGHT_DUE)


def test_door_collectible_without_payment_details_is_zero() -> None:
    assert _pickup_with_payment(None).door_collectible == 0.0


def _machine_accepts(current: PickupStatus, candidate: PickupStatus) -> bool:
    try:
        ShipmentLifecycleMachine.validate_transition(current, candidate)
    except HTTPException:
        return False
    return True


def _next_statuses(current: PickupStatus) -> list[PickupStatus]:
    """The API field under test, read from a PickupRead in `current`."""
    return PickupRead.model_construct(status=current, payment_details=None).allowed_next_statuses


@pytest.mark.parametrize("current", list(PickupStatus))
def test_allowed_next_statuses_match_the_lifecycle_machine(current: PickupStatus) -> None:
    allowed = _next_statuses(current)
    assert current not in allowed
    for candidate in PickupStatus:
        if candidate != current:
            assert (candidate in allowed) == _machine_accepts(current, candidate)


@pytest.mark.parametrize("terminal", sorted(ShipmentLifecycleMachine.TERMINAL_STATUSES))
def test_terminal_statuses_offer_no_next_move(terminal: PickupStatus) -> None:
    assert _next_statuses(terminal) == []


def test_out_for_delivery_offers_delivery_ndr_and_rto() -> None:
    allowed = set(_next_statuses(PickupStatus.OUT_FOR_DELIVERY))
    assert {PickupStatus.COMPLETED, PickupStatus.EXCEPTION, PickupStatus.RTO_INITIATED} <= allowed
    assert PickupStatus.OPEN not in allowed


def test_rto_never_offers_delivered() -> None:
    for rto in ShipmentLifecycleMachine.RTO_STATUSES:
        assert PickupStatus.COMPLETED not in _next_statuses(rto)


def test_computed_field_is_serialised() -> None:
    pickup = PickupRead.model_construct(status=PickupStatus.RTO_IN_TRANSIT, payment_details=None)
    assert pickup.allowed_next_statuses == ShipmentLifecycleMachine.allowed_next_statuses(
        PickupStatus.RTO_IN_TRANSIT
    )


def _full_prime_shipment(tenant_id: uuid.UUID, creator_id: uuid.UUID) -> PickupRequest:
    """Builds an in-memory Prime shipment with a transporter snapshot for serializer tests."""
    addr_id = uuid.uuid4()
    address = Address(
        id=addr_id,
        tenant_id=tenant_id,
        user_id=creator_id,
        name="Hub",
        phone="9876543210",
        address_line1="Plot 1",
        city="Delhi",
        state="DL",
        pincode="110001",
    )
    shipment_id = uuid.uuid4()
    payment = PaymentDetails(
        id=uuid.uuid4(),
        pickup_id=shipment_id,
        base_freight=100.0,
        tax_amount=18.0,
        total_logistics_cost=118.0,
        chargeable_weight=10.0,
        carrier_cost={"snapshot": {"transporter_name": "SAMEER TRANSPORT"}},
    )
    pkg = PackageDetails(
        id=uuid.uuid4(),
        pickup_id=shipment_id,
        length=20.0,
        breadth=15.0,
        height=10.0,
        weight=10.0,
        box_count=1,
    )
    shipment = PickupRequest(
        id=shipment_id,
        tenant_id=tenant_id,
        created_by_user_id=creator_id,
        tracking_id="LOGISMART-TEST-PRIME1",
        status=PickupStatus.OPEN,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
        service_option=ServiceOption.PRIME_SURFACE,
        requested_pickup_date=date(2026, 11, 2),
        product_category=ProductCategory.ELECTRONICS,
        pickup_address_id=addr_id,
        delivery_address_id=addr_id,
    )
    shipment.pickup_address = address
    shipment.delivery_address = address
    shipment.packages = [pkg]
    shipment.payment_details = payment
    shipment.documents = []
    return shipment


@pytest.mark.parametrize(
    "staff_role",
    [
        UserRole.owner,
        UserRole.admin,
        UserRole.operations_user,
        UserRole.support_user,
        UserRole.read_only_user,
    ],
)
def test_serialize_shipment_exposes_transporter_name_to_staff_and_clears_for_customer(
    staff_role: UserRole,
) -> None:
    tenant_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    shipment = _full_prime_shipment(tenant_id, customer_id)

    staff_user = User(
        id=uuid.uuid4(), tenant_id=tenant_id, email="staff@t.in", role=staff_role
    )
    staff_read = _serialize_shipment(shipment, staff_user)
    assert staff_read.transporter_name == "SAMEER TRANSPORT"

    # Even on the same cached PickupRequest object, a subsequent customer read gets None.
    customer_user = User(
        id=customer_id, tenant_id=tenant_id, email="cust@t.in", role=UserRole.customer
    )
    customer_read = _serialize_shipment(shipment, customer_user)
    assert customer_read.transporter_name is None
    assert getattr(shipment, "transporter_name", None) is None
    assert "transporter_name" not in PublicTrackingRead.model_fields


@pytest.mark.asyncio
async def test_manifest_get_by_id_supports_for_update_and_sync_after_detach() -> None:
    """Regression test (#699.1): `ManifestRepository.get_manifest_by_id(..., for_update=True)`."""
    tenant_id = uuid.uuid4()
    manifest_id = uuid.uuid4()
    shipment_id = uuid.uuid4()

    manifest = Manifest(
        id=manifest_id,
        tenant_id=tenant_id,
        pickup_request_number="123456789",
        status=ManifestStatus.SCHEDULED,
        scheduled_date=date(2026, 11, 2),
        slot_start_time=time(10, 0),
        slot_end_time=time(14, 0),
        total_boxes=2,
    )
    manifest.pickups = []
    executed_queries: list[object] = []

    class _FakeResult:
        def first(self) -> Manifest:
            return manifest

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        async def exec(self, query: object) -> _FakeResult:
            executed_queries.append(query)
            return _FakeResult()

        def add(self, obj: object) -> None:
            self.added.append(obj)

    session = _FakeSession()
    repo = ManifestRepository(session)  # type: ignore[arg-type]

    res_unlocked = await repo.get_manifest_by_id(manifest_id, tenant_id, for_update=False)
    assert res_unlocked is manifest
    assert getattr(executed_queries[-1], "_for_update_arg", None) is None

    res_locked = await repo.get_manifest_by_id(manifest_id, tenant_id, for_update=True)
    assert res_locked is manifest
    assert getattr(executed_queries[-1], "_for_update_arg", None) is not None

    service = ShipmentService(ShipmentRepository(session))  # type: ignore[arg-type]
    await service._sync_manifest_after_detach(manifest_id, shipment_id, tenant_id)
    assert manifest.total_boxes == 0
    assert manifest.status == ManifestStatus.CANCELED
    assert manifest in session.added


def test_serialize_shipment_accepts_ownerless_addresses_and_activities() -> None:
    """BUG-04: `Address.user_id` is nullable, so `PickupRead` and `ShipmentActivityRead` must accept `user_id=None`."""
    tenant_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    shipment = _full_prime_shipment(tenant_id, creator_id)
    shipment.pickup_address.user_id = None
    shipment.delivery_address.user_id = None

    staff_user = User(
        id=uuid.uuid4(), tenant_id=tenant_id, email="ops@t.in", role=UserRole.operations_user
    )
    read = _serialize_shipment(shipment, staff_user)
    assert read.pickup_address.user_id is None
    assert read.delivery_address.user_id is None

    activity = ShipmentActivity.model_construct(
        id=uuid.uuid4(),
        pickup_id=shipment.id,
        user_id=None,
        timestamp=datetime(2026, 11, 4, 7, 30, tzinfo=timezone.utc),
        activity_type=ActivityType.STATUS_CHANGE,
        is_public=True,
        summary="In transit",
        comment=None,
        diff={},
    )
    activity_read = ShipmentActivityRead.model_validate(activity)
    assert activity_read.user_id is None


def test_serialize_shipment_list_skips_corrupt_row_without_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BUG-04: a single corrupt row in a list response is logged and skipped instead of 500ing the whole page."""
    tenant_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    good = _full_prime_shipment(tenant_id, creator_id)
    corrupt = _full_prime_shipment(tenant_id, creator_id)
    corrupt.tracking_id = "LOGISMART-TEST-BADROW"
    object.__setattr__(corrupt, "pickup_address", None)

    staff_user = User(
        id=uuid.uuid4(), tenant_id=tenant_id, email="ops@t.in", role=UserRole.operations_user
    )
    parsed = _serialize_shipment_list([corrupt, good], staff_user)
    assert [row.id for row in parsed] == [good.id]
    assert "LOGISMART-TEST-BADROW" in caplog.text


def test_serialize_cancelled_shipment_zeroes_freight_charges() -> None:
    """BUG-07: a cancelled / QC-failed shipment serializes `0.0` freight charges."""
    tenant_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    shipment = _full_prime_shipment(tenant_id, creator_id)
    shipment.status = PickupStatus.CANCELLED
    customer = User(
        id=creator_id, tenant_id=tenant_id, email="cust@t.in", role=UserRole.customer
    )
    read = _serialize_shipment(shipment, customer)
    assert read.payment_details.total_logistics_cost == 0.0
    assert read.payment_details.base_freight == 0.0
    assert read.payment_details.tax_amount == 0.0


