"""
Unit test for the Phase C shipment state machine (plan C1 / H-6): walks every status pair.

Pure: no database, no app. Spring analogy: a parameterised JUnit test over a Spring
Statemachine's transition table.
"""

import itertools

import pytest
from fastapi import HTTPException

from app.models.pickups import PickupStatus
from app.services.shipment_lifecycle import ShipmentLifecycleMachine

TERMINAL = {
    PickupStatus.COMPLETED,
    PickupStatus.RTO_DELIVERED,
    PickupStatus.CANCELLED,
    PickupStatus.QC_FAILED,
    PickupStatus.REJECTED_AT_PICKUP,
}
RTO = {PickupStatus.RTO_INITIATED, PickupStatus.RTO_IN_TRANSIT, PickupStatus.RTO_DELIVERED}
PRE_PICKUP = {PickupStatus.DRAFT, PickupStatus.OPEN, PickupStatus.ASSIGNED}
PICKUP_REJECTIONS = {PickupStatus.QC_FAILED, PickupStatus.REJECTED_AT_PICKUP}

EXPECTED_ALLOWED = {
    (PickupStatus.DRAFT, PickupStatus.OPEN),
    (PickupStatus.DRAFT, PickupStatus.CANCELLED),
    (PickupStatus.OPEN, PickupStatus.ASSIGNED),
    (PickupStatus.OPEN, PickupStatus.CANCELLED),
    (PickupStatus.OPEN, PickupStatus.QC_FAILED),
    (PickupStatus.OPEN, PickupStatus.REJECTED_AT_PICKUP),
    (PickupStatus.ASSIGNED, PickupStatus.IN_TRANSIT),
    (PickupStatus.ASSIGNED, PickupStatus.CANCELLED),
    (PickupStatus.ASSIGNED, PickupStatus.EXCEPTION),
    (PickupStatus.ASSIGNED, PickupStatus.QC_FAILED),
    (PickupStatus.ASSIGNED, PickupStatus.REJECTED_AT_PICKUP),
    (PickupStatus.IN_TRANSIT, PickupStatus.OUT_FOR_DELIVERY),
    (PickupStatus.IN_TRANSIT, PickupStatus.COMPLETED),
    (PickupStatus.IN_TRANSIT, PickupStatus.RTO_INITIATED),
    (PickupStatus.IN_TRANSIT, PickupStatus.EXCEPTION),
    (PickupStatus.IN_TRANSIT, PickupStatus.LOST),
    (PickupStatus.OUT_FOR_DELIVERY, PickupStatus.COMPLETED),
    (PickupStatus.OUT_FOR_DELIVERY, PickupStatus.RTO_INITIATED),
    (PickupStatus.OUT_FOR_DELIVERY, PickupStatus.EXCEPTION),
    (PickupStatus.OUT_FOR_DELIVERY, PickupStatus.LOST),
    (PickupStatus.EXCEPTION, PickupStatus.OPEN),  # D-04: resume to the held stage
    (PickupStatus.EXCEPTION, PickupStatus.ASSIGNED),
    (PickupStatus.EXCEPTION, PickupStatus.IN_TRANSIT),
    (PickupStatus.EXCEPTION, PickupStatus.OUT_FOR_DELIVERY),
    (PickupStatus.EXCEPTION, PickupStatus.RTO_INITIATED),
    (PickupStatus.EXCEPTION, PickupStatus.RTO_IN_TRANSIT),
    (PickupStatus.EXCEPTION, PickupStatus.CANCELLED),
    (PickupStatus.EXCEPTION, PickupStatus.LOST),
    (PickupStatus.RTO_INITIATED, PickupStatus.RTO_IN_TRANSIT),
    (PickupStatus.RTO_INITIATED, PickupStatus.RTO_DELIVERED),
    (PickupStatus.RTO_INITIATED, PickupStatus.EXCEPTION),
    (PickupStatus.RTO_INITIATED, PickupStatus.LOST),
    (PickupStatus.RTO_IN_TRANSIT, PickupStatus.RTO_DELIVERED),
    (PickupStatus.RTO_IN_TRANSIT, PickupStatus.EXCEPTION),
    (PickupStatus.RTO_IN_TRANSIT, PickupStatus.LOST),
    (PickupStatus.LOST, PickupStatus.IN_TRANSIT),
    (PickupStatus.LOST, PickupStatus.RTO_INITIATED),
}
"""Every allowed move between two different statuses (the plan's C1 lenient + hard rules)."""

ALL_PAIRS = [(a, b) for a, b in itertools.product(PickupStatus, PickupStatus) if a != b]


def _allowed(current: PickupStatus, new: PickupStatus) -> bool:
    """True when the machine accepts the move."""
    try:
        ShipmentLifecycleMachine.validate_transition(current, new)
    except HTTPException as exc:
        assert exc.status_code == 400
        return False
    return True


@pytest.mark.parametrize(("current", "new"), ALL_PAIRS, ids=lambda s: s.value)
def test_transition_matches_table(current: PickupStatus, new: PickupStatus) -> None:
    """Each pair is allowed exactly when it is in the expected table."""
    assert _allowed(current, new) is ((current, new) in EXPECTED_ALLOWED)


@pytest.mark.parametrize("status", list(PickupStatus), ids=lambda s: s.value)
def test_same_status_is_a_no_op(status: PickupStatus) -> None:
    """Saving details without a status change never raises."""
    ShipmentLifecycleMachine.validate_transition(status, status)


def test_hard_rules_hold_over_the_table() -> None:
    """H-6 invariants, stated independently of the table above."""
    for current, new in EXPECTED_ALLOWED:
        assert current not in TERMINAL, f"left terminal {current}"
        assert not (current in RTO and new == PickupStatus.COMPLETED), "RTO became Delivered"
        if new in PICKUP_REJECTIONS:
            assert current in PRE_PICKUP, f"{new} reached after pickup from {current}"
    assert PickupStatus.LOST not in TERMINAL
    assert ShipmentLifecycleMachine.TERMINAL_STATUSES == TERMINAL
    assert ShipmentLifecycleMachine.RTO_STATUSES == RTO
