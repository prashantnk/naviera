"""
Pure unit tests (no DB) for the read-only ops fields on `PickupRead` (WP2 / E-06 / E-11).

- `door_collectible` must come from `services.cod_payout.door_collectible` (never the FE).
- `allowed_next_statuses` must mirror `ShipmentLifecycleMachine` exactly.
"""

import pytest
from fastapi import HTTPException

from app.models.pickups import PickupStatus
from app.schemas.v1.pickups import PaymentDetailsRead, PickupRead
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
