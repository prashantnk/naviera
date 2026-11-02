"""
Pure unit tests for the WP4 NDR / status guard (A-09, A-21, A-22, D-04, D-05, D-08 rules
that live in `ndr_rules` and `ShipmentLifecycleMachine`). No app, no database.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.pickups import NdrAction, NdrExceptionReason, PickupStatus, ShipmentType
from app.repositories.shipments import parse_held_from
from app.services import ndr_rules
from app.services.exceptions import ExceptionsService
from app.services.shipment import ShipmentService
from app.services.shipment_lifecycle import ShipmentLifecycleMachine

FWD = ShipmentType.FORWARD
REV = ShipmentType.REVERSE
R = NdrExceptionReason
S = PickupStatus
GST = Decimal("0.18")


# --- raise_rejection (A-21, D-04b) ------------------------------------------------


@pytest.mark.parametrize("held_from", [S.IN_TRANSIT, S.OUT_FOR_DELIVERY, S.RTO_IN_TRANSIT])
def test_pickup_failed_after_pickup_is_refused(held_from: PickupStatus) -> None:
    assert ndr_rules.raise_rejection(R.PICKUP_FAILED, FWD, held_from) == (
        ndr_rules.PICKUP_FAILED_AFTER_PICKUP_DETAIL
    )


@pytest.mark.parametrize("reason", sorted(ndr_rules.DELIVERY_ATTEMPT_REASONS, key=lambda r: r.value))
def test_delivery_attempt_on_unpicked_forward_parcel_is_refused(reason: NdrExceptionReason) -> None:
    assert ndr_rules.raise_rejection(reason, FWD, S.ASSIGNED) == (
        ndr_rules.DELIVERY_REASON_BEFORE_PICKUP_DETAIL
    )


def test_allowed_raises() -> None:
    assert ndr_rules.raise_rejection(R.PICKUP_FAILED, FWD, S.ASSIGNED) is None
    assert ndr_rules.raise_rejection(R.CONSIGNEE_UNAVAILABLE, REV, S.ASSIGNED) is None
    assert ndr_rules.raise_rejection(R.CONSIGNEE_UNAVAILABLE, FWD, S.OUT_FOR_DELIVERY) is None
    assert ndr_rules.raise_rejection(R.DAMAGED, FWD, S.ASSIGNED) is None


# --- stage-aware pickup stage / resume / attempt limit (A-21, D-04a) ---------------


def test_reverse_parcel_already_picked_up_is_not_pickup_stage() -> None:
    assert ndr_rules.is_pickup_stage(R.CONSIGNEE_UNAVAILABLE, REV, S.ASSIGNED)
    assert not ndr_rules.is_pickup_stage(R.CONSIGNEE_UNAVAILABLE, REV, S.IN_TRANSIT)
    # 3 strikes on the way back to the merchant never auto-cancel with a full refund.
    assert ndr_rules.attempt_limit_outcome(R.CONSIGNEE_UNAVAILABLE, REV, 3, S.IN_TRANSIT) is None
    assert (
        ndr_rules.attempt_limit_outcome(R.CONSIGNEE_UNAVAILABLE, REV, 3, S.ASSIGNED)
        == S.CANCELLED
    )


def test_legacy_rows_without_held_from_keep_reason_rules() -> None:
    assert ndr_rules.is_pickup_stage(R.PICKUP_FAILED, FWD)
    assert ndr_rules.is_pickup_stage(R.CONSIGNEE_REFUSED, REV)
    assert ndr_rules.resume_status(R.CONSIGNEE_REFUSED, FWD, False) == S.IN_TRANSIT
    assert ndr_rules.resume_status(R.PICKUP_FAILED, FWD, True) == S.ASSIGNED
    assert ndr_rules.attempt_limit_outcome(R.CONSIGNEE_REFUSED, FWD, 3) == S.RTO_INITIATED


@pytest.mark.parametrize(
    ("held_from", "has_pur", "expected"),
    [
        (S.ASSIGNED, True, S.ASSIGNED),
        (S.ASSIGNED, False, S.OPEN),
        (S.IN_TRANSIT, True, S.IN_TRANSIT),
        (S.OUT_FOR_DELIVERY, True, S.IN_TRANSIT),
        (S.RTO_INITIATED, True, S.RTO_INITIATED),
        (S.RTO_IN_TRANSIT, True, S.RTO_IN_TRANSIT),
    ],
)
def test_resume_returns_to_held_stage(
    held_from: PickupStatus, has_pur: bool, expected: PickupStatus
) -> None:
    assert ndr_rules.resume_status(R.DAMAGED, FWD, has_pur, held_from) == expected
    ShipmentLifecycleMachine.validate_transition(S.EXCEPTION, expected)


def test_rto_leg_exception_never_resumes_forward_or_reruns_rto() -> None:
    actions = ndr_rules.allowed_actions(R.CONSIGNEE_UNAVAILABLE, FWD, False, S.RTO_IN_TRANSIT)
    assert NdrAction.RETURN_TO_ORIGIN not in actions
    assert NdrAction.REATTEMPT in actions
    payment = ndr_rules.allowed_actions(R.PAYMENT_DISPUTE, FWD, False, S.RTO_IN_TRANSIT)
    assert NdrAction.UPDATE_PAYMENT_MODE not in payment
    assert ndr_rules.attempt_limit_outcome(R.CONSIGNEE_REFUSED, FWD, 5, S.RTO_IN_TRANSIT) is None


def test_unpicked_parcel_offers_no_rto() -> None:
    actions = ndr_rules.allowed_actions(R.DAMAGED, FWD, False, S.ASSIGNED)
    assert NdrAction.RETURN_TO_ORIGIN not in actions
    assert ndr_rules.allowed_actions(R.PICKUP_FAILED, FWD, False, S.ASSIGNED) == list(
        ndr_rules.PICKUP_STAGE_ACTIONS
    )


def test_forward_delivery_attempts_still_auto_rto() -> None:
    assert (
        ndr_rules.attempt_limit_outcome(R.CONSIGNEE_REFUSED, FWD, 3, S.OUT_FOR_DELIVERY)
        == S.RTO_INITIATED
    )
    assert ndr_rules.attempt_limit_outcome(R.CONSIGNEE_REFUSED, FWD, 2, S.IN_TRANSIT) is None


def test_consent_actions_cover_money_and_door_collection() -> None:
    assert {
        NdrAction.RETURN_TO_ORIGIN,
        NdrAction.UPDATE_PAYMENT_MODE,
        NdrAction.ACKNOWLEDGE_CHARGES,
        NdrAction.ACCEPT_WEIGHT,
    } <= ndr_rules.CONSENT_ACTIONS


# --- lifecycle machine (E-11 allowed_next_statuses) -------------------------------


def test_allowed_next_statuses_match_validate_transition() -> None:
    for current in PickupStatus:
        allowed = ShipmentLifecycleMachine.allowed_next_statuses(current)
        for candidate in PickupStatus:
            if candidate == current:
                continue
            if candidate in allowed:
                ShipmentLifecycleMachine.validate_transition(current, candidate)
            else:
                with pytest.raises(HTTPException):
                    ShipmentLifecycleMachine.validate_transition(current, candidate)


def test_terminal_statuses_have_no_next() -> None:
    for terminal in ShipmentLifecycleMachine.TERMINAL_STATUSES:
        assert ShipmentLifecycleMachine.allowed_next_statuses(terminal) == []


# --- held_from parsing --------------------------------------------------------------


def test_parse_held_from() -> None:
    assert parse_held_from("IN_TRANSIT") == S.IN_TRANSIT
    assert parse_held_from(None) is None
    assert parse_held_from("NOT_A_STATUS") is None
    assert parse_held_from("EXCEPTION") is None


# --- ShipmentService static guards --------------------------------------------------


def _shipment(**fields):
    defaults = dict(
        status=S.EXCEPTION,
        ndr_reason=R.DAMAGED,
        shipment_type=FWD,
        manifest_id=None,
        delivery_otp=None,
        charge_amount=None,
    )
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def test_ensure_delivery_otp_only_on_the_way_to_consignee() -> None:
    in_transit = _shipment(status=S.IN_TRANSIT)
    diff = ShipmentService.ensure_delivery_otp(in_transit)
    assert in_transit.delivery_otp and len(in_transit.delivery_otp) == 6
    assert diff["delivery_otp"]["new"] == in_transit.delivery_otp
    assert ShipmentService.ensure_delivery_otp(in_transit) == {}  # never regenerated
    assigned = _shipment(status=S.ASSIGNED)
    assert ShipmentService.ensure_delivery_otp(assigned) == {}
    assert assigned.delivery_otp is None


def _user(role):
    return SimpleNamespace(role=role, id=None)


@pytest.mark.parametrize("target", [S.LOST, S.RTO_INITIATED])
def test_operations_user_cannot_lose_or_rto(target: PickupStatus) -> None:
    from app.models.tenants import UserRole

    with pytest.raises(HTTPException) as exc:
        ShipmentService._assert_status_change_role(
            _user(UserRole.operations_user), target, S.IN_TRANSIT, cancel_converted=False
        )
    assert exc.value.status_code == 403
    ShipmentService._assert_status_change_role(
        _user(UserRole.admin), target, S.IN_TRANSIT, cancel_converted=False
    )


def test_operations_user_cannot_mark_lost_found_but_can_run_normal_moves() -> None:
    from app.models.tenants import UserRole

    ops = _user(UserRole.operations_user)
    with pytest.raises(HTTPException):
        ShipmentService._assert_status_change_role(ops, S.IN_TRANSIT, S.LOST, False)
    ShipmentService._assert_status_change_role(ops, S.OUT_FOR_DELIVERY, S.IN_TRANSIT, False)
    ShipmentService._assert_status_change_role(ops, S.RTO_INITIATED, S.IN_TRANSIT, True)


def test_manual_exception_exit_must_match_held_stage() -> None:
    held_pre_pickup = _shipment(manifest_id="pur")
    with pytest.raises(HTTPException):
        ShipmentService._assert_exception_exit(held_pre_pickup, S.IN_TRANSIT, S.ASSIGNED)
    ShipmentService._assert_exception_exit(held_pre_pickup, S.ASSIGNED, S.ASSIGNED)
    held_rto = _shipment()
    with pytest.raises(HTTPException):
        ShipmentService._assert_exception_exit(held_rto, S.IN_TRANSIT, S.RTO_IN_TRANSIT)
    ShipmentService._assert_exception_exit(held_rto, S.RTO_IN_TRANSIT, S.RTO_IN_TRANSIT)
    held_ofd = _shipment()
    ShipmentService._assert_exception_exit(held_ofd, S.OUT_FOR_DELIVERY, S.OUT_FOR_DELIVERY)
    ShipmentService._assert_exception_exit(held_ofd, S.LOST, S.OUT_FOR_DELIVERY)


def test_is_after_pickup_uses_held_from() -> None:
    reverse_on_way_back = _shipment(ndr_reason=R.CONSIGNEE_UNAVAILABLE, shipment_type=REV)
    assert not ShipmentService.is_after_pickup(reverse_on_way_back)  # legacy rule
    assert ShipmentService.is_after_pickup(reverse_on_way_back, S.IN_TRANSIT)
    document_before_pickup = _shipment(ndr_reason=R.DOCUMENT_NEEDED)
    assert not ShipmentService.is_after_pickup(document_before_pickup, S.ASSIGNED)


# --- A-20 payable charge ------------------------------------------------------------


def test_charge_amount_payable_adds_gst_only_to_gst_exclusive_charges() -> None:
    mathadi = _shipment(ndr_reason=R.ADDITIONAL_CHARGES, charge_amount=1000.0)
    assert ExceptionsService.charge_amount_payable(mathadi, GST) == 1180.0
    freight = _shipment(ndr_reason=R.FREIGHT_COLLECTION, charge_amount=1180.0)
    assert ExceptionsService.charge_amount_payable(freight, GST) == 1180.0
    weight = _shipment(ndr_reason=R.WEIGHT_DISCREPANCY, charge_amount=50.0)
    assert ExceptionsService.charge_amount_payable(weight, GST) == 59.0
    assert ExceptionsService.charge_amount_payable(_shipment(), GST) is None


# --- A-09 liability flag ------------------------------------------------------------


def test_shipper_cannot_send_logismart_liable() -> None:
    from app.models.tenants import UserRole
    from app.schemas.v1.exceptions import NdrActionRequest

    request = NdrActionRequest(action=NdrAction.RETURN_TO_ORIGIN, logismart_liable=True)
    with pytest.raises(HTTPException) as exc:
        ExceptionsService._assert_liability_flag_allowed(request, _user(UserRole.customer))
    assert exc.value.status_code == 403
    ExceptionsService._assert_liability_flag_allowed(request, _user(UserRole.admin))
    plain = NdrActionRequest(action=NdrAction.RETURN_TO_ORIGIN)
    ExceptionsService._assert_liability_flag_allowed(plain, _user(UserRole.customer))
