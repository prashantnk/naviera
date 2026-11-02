"""Pure unit tests for WP2 (A-10) and WP3 (A-07, A-08, A-11, A-25, C-09)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.delhivery_modules import WeightDisputeClaimStatus
from app.models.pickups import DimensionUnit, PickupStatus, WeightUnit
from app.models.tenants import UserRole
from app.schemas.v1.delhivery_modules import (
    WeightDisputeClaimCreate,
    WeightDisputeResolveRequest,
)
from app.schemas.v1.manifests import ManifestDispatchMeasurement
from app.schemas.v1.pickups import PickupUpdate
from app.services.delhivery_modules import DelhiveryModulesService
from app.services.manifests import ManifestService
from app.services.repricing import EditField, EditNotAllowedError, assert_edit_allowed


def test_a10_cod_fields_frozen_after_in_transit_for_all_roles() -> None:
    """A-10 (H-12): EditField.COD is frozen once OUT_FOR_DELIVERY, even for owner/admin."""
    shipment = SimpleNamespace(status=PickupStatus.OUT_FOR_DELIVERY, manifest_id=None)
    for role in (UserRole.owner, UserRole.admin, UserRole.customer):
        actor = SimpleNamespace(id=uuid4(), role=role)
        with pytest.raises(EditNotAllowedError) as exc:
            assert_edit_allowed(shipment, {EditField.COD}, actor)
        assert exc.value.status_code == 400
        assert "H-12" in str(exc.value.detail)


def test_a10_cod_fields_forbidden_for_ops_and_support_at_all_statuses() -> None:
    """A-10: operations_user and support_user cannot edit COD or payment mode even at OPEN."""
    shipment = SimpleNamespace(status=PickupStatus.OPEN, manifest_id=None)
    for role in (UserRole.operations_user, UserRole.support_user):
        actor = SimpleNamespace(id=uuid4(), role=role)
        with pytest.raises(EditNotAllowedError) as exc:
            assert_edit_allowed(shipment, {EditField.COD}, actor)
        assert exc.value.status_code == 403


def test_a10_pickup_update_schema_has_expected_cod_amount() -> None:
    """A-10: PickupUpdate accepts expected_cod_amount for COMPLETED concurrency check."""
    payload = PickupUpdate(
        status=PickupStatus.COMPLETED,
        expected_cod_amount=Decimal("1250.00"),
    )
    assert payload.expected_cod_amount == Decimal("1250.00")


@pytest.mark.asyncio
async def test_a08_raise_weight_claims_guards() -> None:
    """A-08: raise_weight_claims rejects multi-AWB, already-raised (409), zero cost diff, and claimed >= charged."""
    tenant_id = uuid4()
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, role=UserRole.customer, email="merchant@example.com")
    repo = MagicMock()
    svc = DelhiveryModulesService(repo=repo)

    # Case 0: multi-AWB bulk claim -> 400
    with pytest.raises(HTTPException) as exc_multi:
        await svc.raise_weight_claims(
            user=user,
            tenant_id=tenant_id,
            payload=WeightDisputeClaimCreate(
                tracking_ids=["AWB1", "AWB2"],
                claimed_weight_g=500,
            ),
        )
    assert exc_multi.value.status_code == 400

    shipment = SimpleNamespace(id=uuid4(), created_by_user_id=user_id, tenant_id=tenant_id)
    repo.find_shipment_by_tracking_id = AsyncMock(return_value=shipment)

    # Case 1: already CLAIM_RAISED -> 409
    dispute_raised = SimpleNamespace(
        id=uuid4(),
        tracking_id="LS2610300001",
        claim_status=WeightDisputeClaimStatus.CLAIM_RAISED.value,
        charged_weight_g=2000.0,
        manifested_weight_g=500.0,
        cost_diff_inr=120.0,
    )
    repo.get_weight_dispute_by_tracking_id = AsyncMock(return_value=dispute_raised)
    with pytest.raises(HTTPException) as exc_409:
        await svc.raise_weight_claims(
            user=user,
            tenant_id=tenant_id,
            payload=WeightDisputeClaimCreate(
                tracking_ids=["LS2610300001"],
                claimed_weight_g=1000,
            ),
        )
    assert exc_409.value.status_code == 409

    # Case 2: claimed_weight_g >= charged_weight_g -> 400
    dispute_none = SimpleNamespace(
        id=uuid4(),
        tracking_id="LS2610300002",
        claim_status=WeightDisputeClaimStatus.NONE.value,
        charged_weight_g=2000.0,
        manifested_weight_g=500.0,
        cost_diff_inr=120.0,
    )
    repo.get_weight_dispute_by_tracking_id = AsyncMock(return_value=dispute_none)
    with pytest.raises(HTTPException) as exc_ge:
        await svc.raise_weight_claims(
            user=user,
            tenant_id=tenant_id,
            payload=WeightDisputeClaimCreate(
                tracking_ids=["LS2610300002"],
                claimed_weight_g=2000,
            ),
        )
    assert exc_ge.value.status_code == 400

    # Case 3: cost_diff_inr <= 0 -> 400
    dispute_zero_diff = SimpleNamespace(
        id=uuid4(),
        tracking_id="LS2610300003",
        claim_status=WeightDisputeClaimStatus.NONE.value,
        charged_weight_g=2000.0,
        manifested_weight_g=500.0,
        cost_diff_inr=0.0,
    )
    repo.get_weight_dispute_by_tracking_id = AsyncMock(return_value=dispute_zero_diff)
    with pytest.raises(HTTPException) as exc_zero:
        await svc.raise_weight_claims(
            user=user,
            tenant_id=tenant_id,
            payload=WeightDisputeClaimCreate(
                tracking_ids=["LS2610300003"],
                claimed_weight_g=1000,
            ),
        )
    assert exc_zero.value.status_code == 400


@pytest.mark.asyncio
async def test_a07_resolve_weight_dispute_status_and_expected_weight_guards() -> None:
    """A-07/A-08: resolve_weight_dispute requires CLAIM_RAISED and checks expected_claimed_weight_g."""
    tenant_id = uuid4()
    dispute_id = uuid4()
    admin = SimpleNamespace(id=uuid4(), role=UserRole.admin, email="admin@example.com")
    repo = MagicMock()
    svc = DelhiveryModulesService(repo=repo)

    # Reject resolving when status is NONE
    dispute_none = SimpleNamespace(
        id=dispute_id,
        tracking_id="LS2610300004",
        shipment_id=uuid4(),
        claim_status=WeightDisputeClaimStatus.NONE.value,
        claimed_weight_g=None,
        charged_weight_g=2000.0,
        manifested_weight_g=500.0,
        cost_diff_inr=100.0,
    )
    repo.get_weight_dispute_by_id = AsyncMock(return_value=dispute_none)
    with pytest.raises(HTTPException) as exc_none:
        await svc.resolve_weight_dispute(
            admin_user=admin,
            tenant_id=tenant_id,
            dispute_id=dispute_id,
            payload=WeightDisputeResolveRequest(claim_status="ACCEPTED"),
        )
    assert exc_none.value.status_code == 400

    # Reject resolving when expected_claimed_weight_g mismatches -> 409
    dispute_raised = SimpleNamespace(
        id=dispute_id,
        tracking_id="LS2610300005",
        shipment_id=uuid4(),
        claim_status=WeightDisputeClaimStatus.CLAIM_RAISED.value,
        claimed_weight_g=800.0,
        charged_weight_g=2000.0,
        manifested_weight_g=500.0,
        cost_diff_inr=100.0,
    )
    repo.get_weight_dispute_by_id = AsyncMock(return_value=dispute_raised)
    with pytest.raises(HTTPException) as exc_mismatch:
        await svc.resolve_weight_dispute(
            admin_user=admin,
            tenant_id=tenant_id,
            dispute_id=dispute_id,
            payload=WeightDisputeResolveRequest(
                claim_status="ACCEPTED",
                expected_claimed_weight_g=600,
            ),
        )
    assert exc_mismatch.value.status_code == 409


def test_a11_manifest_dispatch_measurement_does_not_invent_10kg_boxes() -> None:
    """A-11: _resolve_dispatch_packages scales declared packages or returns (None, actual) when blind."""
    shipment_id = uuid4()
    blind_shipment = SimpleNamespace(
        id=shipment_id,
        is_blind_pickup=True,
        packages=[
            SimpleNamespace(
                box_count=2,
                length=0.0,
                breadth=0.0,
                height=0.0,
                weight=0.0,
                weight_unit=WeightUnit.KG,
                dimension_unit=DimensionUnit.CM,
                packaging_type=None,
                description=None,
            )
        ],
    )
    meas = ManifestDispatchMeasurement(shipment_id=shipment_id, actual_pieces=5)
    pkgs, pieces = ManifestService._resolve_dispatch_packages(blind_shipment, meas)
    assert pkgs is None
    assert pieces == 5

    # Declared B2B LR with 1 box of 20x20x20 cm, 8 kg -> scales box_count to 3
    declared_shipment = SimpleNamespace(
        id=shipment_id,
        is_blind_pickup=False,
        packages=[
            SimpleNamespace(
                box_count=1,
                length=20.0,
                breadth=20.0,
                height=20.0,
                weight=8.0,
                weight_unit=WeightUnit.KG,
                dimension_unit=DimensionUnit.CM,
                packaging_type="BOX",
                description="Cartons",
            )
        ],
    )
    scaled_pkgs, scaled_pieces = ManifestService._resolve_dispatch_packages(
        declared_shipment,
        ManifestDispatchMeasurement(shipment_id=shipment_id, actual_pieces=3),
    )
    assert scaled_pkgs is not None
    assert scaled_pieces == 3
    assert sum(p.box_count for p in scaled_pkgs) == 3
    assert scaled_pkgs[0].weight == 8.0


def test_c09_record_or_update_weight_dispute_does_not_invent_fake_dims() -> None:
    """C-09: No fake '39 x 30 x 6 cm' or '23.8 x 31.8 x 7.3 cm' fallback strings."""
    assert not hasattr(DelhiveryModulesService, "DEFAULT_MANIFESTED_DIMS")
    assert not hasattr(DelhiveryModulesService, "DEFAULT_CHARGED_DIMS")
