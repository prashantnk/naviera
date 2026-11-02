"""
Pure unit tests for the re-pricing HTTP schemas and thin controllers owned by reprice-api (plan B8, B9, B13).

No database required: exercises request validation, mapping from reprice-core dataclasses onto the UI JSON
contract, preview 200-with-rejected_fields handling, customer-scoped charges lookup, and Idempotency-Key replay.
Run: poetry run python -m pytest scripts/tests/test_repricing_api_schemas.py -q
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, List, Optional, Sequence, Tuple

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.v1.endpoints.shipments import (
    _to_measurement_input,
    list_shipment_charges,
    preview_shipment_reprice,
    record_shipment_measurement,
)
from app.core.idempotency import IdempotencyContext
from app.models.pickups import (
    FreightPaymentMode,
    PickupStatus,
    ServiceType,
    ShipmentType,
)
from app.models.repricing import ChargeAdjustmentReason, MeasurementSource
from app.models.tenants import UserRole
from app.schemas.v1.manifests import ManifestDispatchRequest
from app.schemas.v1.pickups import PaymentDetailsRead, PickupUpdate
from app.schemas.v1.repricing import (
    NO_CHANGE_MESSAGE,
    ChargeAdjustmentRead,
    MeasurementCreate,
    RejectedField,
    RejectionRule,
    RepricePreviewResponse,
    SettlementAction,
)
from app.services.repricing import ChargeAdjustmentView, ServiceTypeLockedError

PACKAGE = {"length": 30, "breadth": 30, "height": 30, "weight": 3.5, "box_count": 4}


@dataclass(frozen=True)
class FakePreview:
    """Duck-typed stand-in for reprice-core's RepricePreview."""

    settlement: str
    wallet_delta: Decimal
    note_type: Optional[str]
    shipment_id: uuid.UUID = field(default_factory=uuid.uuid4)
    reason: ChargeAdjustmentReason = ChargeAdjustmentReason.PICKUP_MEASUREMENT
    old_total: Decimal = Decimal("1197.70")
    new_total: Decimal = Decimal("1587.10")
    delta: Decimal = Decimal("389.40")
    old_chargeable_weight: Decimal = Decimal("18.000")
    new_chargeable_weight: Decimal = Decimal("24.000")
    new_breakdown: dict = field(default_factory=lambda: {"base_charge": 1200.0})
    freight_payment_mode: FreightPaymentMode = FreightPaymentMode.PREPAID
    old_cod_amount: Decimal = Decimal("0.00")
    new_cod_amount: Decimal = Decimal("0.00")
    old_freight_collectible: Decimal = Decimal("0.00")
    new_freight_collectible: Decimal = Decimal("0.00")
    collectible_frozen: bool = False
    changed: bool = True
    warnings: Sequence[str] = ()


class FakeRepricingError(HTTPException):
    """Stand-in for reprice-core's RepricingError (rule + field attributes)."""

    def __init__(self, rule: str, field_name: Optional[str], detail: str) -> None:
        super().__init__(status_code=400, detail=detail)
        self.rule = rule
        self.field = field_name


# --- MeasurementCreate -------------------------------------------------------


def test_measurement_accepts_full_packages_with_default_hub_source() -> None:
    body = MeasurementCreate(packages=[PACKAGE])
    assert body.source == MeasurementSource.HUB
    assert body.packages[0].box_count == 4
    assert body.weight_kg is None


def test_measurement_accepts_weight_only() -> None:
    body = MeasurementCreate(weight_kg=14.0, source=MeasurementSource.PICKUP)
    assert body.weight_kg == 14.0
    assert body.packages is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"packages": [PACKAGE], "weight_kg": 14.0}, {"packages": []}],
)
def test_measurement_requires_exactly_one_basis(payload: dict) -> None:
    with pytest.raises(ValidationError):
        MeasurementCreate(**payload)


def test_measurement_rejects_claim_source_over_http() -> None:
    with pytest.raises(ValidationError):
        MeasurementCreate(weight_kg=2.0, source=MeasurementSource.CLAIM)


def test_measurement_rejects_non_http_evidence_and_more_than_three() -> None:
    with pytest.raises(ValidationError):
        MeasurementCreate(weight_kg=2.0, evidence_urls=["ftp://x/y.png"])
    with pytest.raises(ValidationError):
        MeasurementCreate(weight_kg=2.0, evidence_urls=["https://a/1"] * 4)


def test_measurement_cleans_blank_remark_and_urls() -> None:
    body = MeasurementCreate(weight_kg=2.0, remark="   ", evidence_urls=[" https://a/1 ", ""])
    assert body.remark is None
    assert body.evidence_urls == ["https://a/1"]


def test_measurement_rejects_zero_weight() -> None:
    with pytest.raises(ValidationError):
        MeasurementCreate(weight_kg=0)


def test_to_measurement_input_maps_weight_and_packages() -> None:
    weight_in = _to_measurement_input(
        MeasurementCreate(weight_kg=14.25, source=MeasurementSource.HUB, remark="scale")
    )
    assert weight_in.weight_only_kg == Decimal("14.250")
    assert weight_in.packages == ()
    assert weight_in.remark == "scale"

    pkg_in = _to_measurement_input(
        MeasurementCreate(packages=[PACKAGE], source=MeasurementSource.PICKUP)
    )
    assert pkg_in.weight_only_kg is None
    assert len(pkg_in.packages) == 1
    assert pkg_in.packages[0].box_count == 4


# --- Dispatch payload --------------------------------------------------------


def test_dispatch_payload_is_backward_compatible() -> None:
    body = ManifestDispatchRequest(picked_shipment_ids=[uuid.uuid4()])
    assert body.measurements is None


def test_dispatch_payload_accepts_measurements_per_lr() -> None:
    sid = uuid.uuid4()
    body = ManifestDispatchRequest(
        measurements=[{"shipment_id": str(sid), "packages": [PACKAGE]}]
    )
    assert body.measurements[0].shipment_id == sid
    assert body.measurements[0].packages[0].box_count == 4


def test_dispatch_payload_rejects_duplicate_lr_and_empty_packages() -> None:
    sid = str(uuid.uuid4())
    with pytest.raises(ValidationError):
        ManifestDispatchRequest(
            measurements=[
                {"shipment_id": sid, "packages": [PACKAGE]},
                {"shipment_id": sid, "packages": [PACKAGE]},
            ]
        )
    with pytest.raises(ValidationError):
        ManifestDispatchRequest(measurements=[{"shipment_id": sid, "packages": []}])


# --- Preview mapping ---------------------------------------------------------


def test_preview_debit_maps_to_debit_action_and_json_numbers() -> None:
    preview = FakePreview(
        settlement="WALLET_DEBIT", wallet_delta=Decimal("-389.40"), note_type="DEBIT_NOTE"
    )
    body = RepricePreviewResponse.from_preview(preview)
    assert body.settlement_action == SettlementAction.DEBIT
    assert body.settlement_message == "₹389.40 will be deducted from the wallet with a GST debit note."
    payload = json.loads(body.model_dump_json())
    assert payload["new_total"] == 1587.10
    assert payload["delta"] == 389.40
    assert payload["new_chargeable_weight"] == 24.0
    assert payload["rejected_fields"] == []
    assert payload["price_changed"] is True


def test_preview_refund_and_collectible_messages() -> None:
    refund = RepricePreviewResponse.from_preview(
        FakePreview(settlement="WALLET_REFUND", wallet_delta=Decimal("976.45"), note_type="CREDIT_NOTE")
    )
    assert refund.settlement_action == SettlementAction.REFUND
    assert "₹976.45 will be refunded" in refund.settlement_message
    collectible = RepricePreviewResponse.from_preview(
        FakePreview(
            settlement="COLLECTIBLE_CHANGE",
            wallet_delta=Decimal("0.00"),
            note_type=None,
            new_freight_collectible=Decimal("256.65"),
        )
    )
    assert collectible.settlement_action == SettlementAction.COLLECTIBLE
    assert collectible.settlement_message.endswith("₹256.65.")


def test_preview_record_only_maps_to_none() -> None:
    body = RepricePreviewResponse.from_preview(
        FakePreview(settlement="RECORD_ONLY", wallet_delta=Decimal("0.00"), note_type=None)
    )
    assert body.settlement_action == SettlementAction.NONE
    assert body.settlement_message == NO_CHANGE_MESSAGE


def test_unchanged_preview_with_rejection() -> None:
    error = FakeRepricingError("H-8", "service_type", "Service type cannot change after pickup.")
    body = RepricePreviewResponse.unchanged(
        uuid.uuid4(),
        Decimal("159.30"),
        Decimal("2.000"),
        {"base_charge": 100.0},
        rejected=[RejectedField.from_error(error)],
    )
    assert body.delta == Decimal("0.00")
    assert body.new_total == body.old_total == Decimal("159.30")
    assert body.price_changed is False
    assert body.rejected_fields[0].rule == RejectionRule.SERVICE_TYPE_LOCKED
    assert body.rejected_fields[0].field == "service_type"


def test_rejection_with_unknown_rule_falls_back_to_state() -> None:
    error = FakeRepricingError("SOMETHING_NEW", None, "nope")
    row = RejectedField.from_error(error)
    assert row.rule == RejectionRule.STATE
    assert row.field is None
    assert row.message == "nope"


# --- Charges history + shared schema additions ------------------------------


def test_charge_adjustment_read_from_attributes() -> None:
    view = ChargeAdjustmentView(
        id=uuid.uuid4(),
        created_at=datetime(2026, 10, 27),
        reason=ChargeAdjustmentReason.HUB_MEASUREMENT,
        old_total=Decimal("159.30"),
        new_total=Decimal("218.30"),
        delta=Decimal("59.00"),
        old_chargeable_weight=None,
        new_chargeable_weight=None,
        freight_payment_mode=FreightPaymentMode.PREPAID,
        wallet_txn_id=None,
        billing_invoice_id=None,
        note_number="LTST2627D000001",
        note_type="DEBIT_NOTE",
        actor_email="ops@logismart.in",
    )
    row = ChargeAdjustmentRead.model_validate(view)
    assert json.loads(row.model_dump_json())["delta"] == 59.0
    assert row.note_number == "LTST2627D000001"


def test_pickup_update_accepts_service_type() -> None:
    body = PickupUpdate(service_type=ServiceType.AIR)
    assert "service_type" in body.model_fields_set


def test_payment_details_read_freight_collectible_defaults_to_zero() -> None:
    assert PaymentDetailsRead.model_fields["freight_collectible"].default == 0.0


# --- Thin controller unit tests ----------------------------------------------


def _fake_shipment(status_val: PickupStatus = PickupStatus.IN_TRANSIT) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status_val,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
        manifest_id=None,
        order_reference_id="REF-1",
        requested_pickup_date=None,
        pickup_time_slot=None,
        reason_for_return=None,
        qc_required=False,
        qc_notes=None,
        is_blind_pickup=False,
        estimated_box_count=None,
        is_carriers_risk=False,
        po_number=None,
        po_date=None,
        po_expiry_date=None,
        appointment_id=None,
        appointment_start=None,
        appointment_end=None,
        pickup_strategy=None,
        product_category=None,
        other_category_description=None,
        pickup_address_id=uuid.uuid4(),
        delivery_address_id=uuid.uuid4(),
        pickup_address=None,
        delivery_address=None,
        packages=[],
        payment_details=SimpleNamespace(
            total_logistics_cost=159.30,
            chargeable_weight=2.0,
            pricing_breakdown={"base_charge": 100.0},
            is_cod=False,
            cod_amount=0.0,
            shipment_total_value=1000.0,
            add_shipping_to_cod=False,
            freight_payment_mode=FreightPaymentMode.PREPAID,
            freight_collectible=0.0,
        ),
    )


def test_preview_controller_returns_200_with_rejected_field_on_repricing_error() -> None:
    shipment = _fake_shipment(PickupStatus.IN_TRANSIT)
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.admin, is_platform_admin=False)
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="logismart")

    class StubShipmentService:
        async def get_shipment_details(self, **_: Any) -> Any:
            return shipment

    class StubRepricingService:
        async def change_from_update(self, *_: Any) -> Any:
            raise ServiceTypeLockedError()

    res = asyncio.run(
        preview_shipment_reprice(
            shipment_id=shipment.id,
            payload=PickupUpdate(service_type=ServiceType.AIR),
            current_user=user,
            current_tenant=tenant,
            shipment_service=StubShipmentService(),
            repricing_service=StubRepricingService(),
        )
    )
    assert res.price_changed is False
    assert res.old_total == Decimal("159.30")
    assert len(res.rejected_fields) == 1
    assert res.rejected_fields[0].rule == RejectionRule.SERVICE_TYPE_LOCKED
    assert res.rejected_fields[0].field == "service_type"


def test_preview_controller_returns_unchanged_when_no_price_inputs_changed() -> None:
    shipment = _fake_shipment(PickupStatus.OPEN)
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.admin, is_platform_admin=False)
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="logismart")

    class StubShipmentService:
        async def get_shipment_details(self, **_: Any) -> Any:
            return shipment

    class StubRepricingService:
        async def change_from_update(self, *_: Any) -> None:
            return None

    res = asyncio.run(
        preview_shipment_reprice(
            shipment_id=shipment.id,
            payload=PickupUpdate(order_reference_id="REF-2"),
            current_user=user,
            current_tenant=tenant,
            shipment_service=StubShipmentService(),
            repricing_service=StubRepricingService(),
        )
    )
    assert res.price_changed is False
    assert res.rejected_fields == []
    assert res.settlement_message == NO_CHANGE_MESSAGE


def test_charges_controller_scopes_via_get_shipment_details() -> None:
    shipment = _fake_shipment(PickupStatus.IN_TRANSIT)
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.customer, is_platform_admin=False)
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="logismart")
    adj_id = uuid.uuid4()
    seen: List[Tuple[uuid.UUID, uuid.UUID]] = []

    class StubShipmentService:
        async def get_shipment_details(
            self, *, shipment_id: uuid.UUID, user: Any, tenant_id: uuid.UUID
        ) -> Any:
            seen.append((shipment_id, tenant_id))
            return shipment

    class StubRepricingService:
        async def list_adjustment_views(
            self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
        ) -> List[ChargeAdjustmentView]:
            assert shipment_id == shipment.id
            assert tenant_id == tenant.id
            return [
                ChargeAdjustmentView(
                    id=adj_id,
                    created_at=datetime(2026, 10, 27),
                    reason=ChargeAdjustmentReason.PICKUP_MEASUREMENT,
                    old_total=Decimal("100.00"),
                    new_total=Decimal("150.00"),
                    delta=Decimal("50.00"),
                    old_chargeable_weight=Decimal("1.000"),
                    new_chargeable_weight=Decimal("2.000"),
                    freight_payment_mode=FreightPaymentMode.PREPAID,
                    wallet_txn_id=None,
                    billing_invoice_id=None,
                    note_number="LTST2627D000002",
                    note_type="DEBIT_NOTE",
                    actor_email="rider@logismart.in",
                )
            ]

    rows = asyncio.run(
        list_shipment_charges(
            shipment_id=shipment.id,
            current_user=user,
            current_tenant=tenant,
            shipment_service=StubShipmentService(),
            repricing_service=StubRepricingService(),
        )
    )
    assert seen == [(shipment.id, tenant.id)]
    assert len(rows) == 1
    assert rows[0].id == adj_id
    assert rows[0].note_number == "LTST2627D000002"


def test_measurement_controller_short_circuits_on_idempotency_replay() -> None:
    replay_resp = JSONResponse(status_code=200, content={"replayed": True})
    idem = IdempotencyContext(
        endpoint="shipments.measurements",
        key="k-1",
        request_hash="h",
        replay=replay_resp,
    )

    class FailIfCalledService:
        async def record_measurement(self, *_: Any, **__: Any) -> Any:
            raise AssertionError("Should not be called on idempotency replay")

    out = asyncio.run(
        record_shipment_measurement(
            shipment_id=uuid.uuid4(),
            payload=MeasurementCreate(weight_kg=5.0),
            current_user=SimpleNamespace(id=uuid.uuid4()),
            current_tenant=SimpleNamespace(id=uuid.uuid4()),
            shipment_service=FailIfCalledService(),
            repricing_service=SimpleNamespace(),
            idem=idem,
        )
    )
    assert out is replay_resp
