"""Pure unit tests for the public tracking timeline (B-03 allow-list, F-01 wording)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.models.pickups import NdrExceptionReason, PickupStatus
from app.services.public_tracking import (
    CREATION_SUMMARY,
    PUBLIC_EXCEPTION_TEXT,
    PUBLIC_STATUS_TEXT,
    build_public_timeline,
    mask_person_name,
)

T0 = datetime(2026, 10, 30, 6, 0, 0)


@dataclass
class _Activity:
    timestamp: datetime
    summary: str
    diff: Optional[Dict[str, Any]] = None
    comment: Optional[str] = None


def _move(minutes: int, old: PickupStatus, new: PickupStatus, **extra: Any) -> _Activity:
    diff: Dict[str, Any] = {"status": {"old": old.value, "new": new.value}, **extra}
    return _Activity(T0 + timedelta(minutes=minutes), f"Status: {new.value}", diff)


def test_timeline_uses_fixed_text_and_drops_internal_rows() -> None:
    activities = [
        _move(30, PickupStatus.ASSIGNED, PickupStatus.IN_TRANSIT),
        _Activity(T0, CREATION_SUMMARY),
        _Activity(
            T0 + timedelta(minutes=40),
            "Charged weight 1 kg → 3 kg at hub | Wallet Debited: Rs. 100",
            {"repricing": {"delta": 100}},
            comment="Consignee drunk, abusive",
        ),
        _move(
            50,
            PickupStatus.IN_TRANSIT,
            PickupStatus.EXCEPTION,
            ndr_raise={"reason": NdrExceptionReason.ADDITIONAL_CHARGES.value},
        ),
        _move(60, PickupStatus.EXCEPTION, PickupStatus.IN_TRANSIT, ndr_action="ACKNOWLEDGE_CHARGES"),
        _move(70, PickupStatus.IN_TRANSIT, PickupStatus.COMPLETED),
    ]
    events = build_public_timeline(activities)
    titles = [event.title for event in events]
    assert titles == ["Order placed", "In transit", "Shipment on hold", "In transit", "Delivered"]
    blob = " ".join(f"{e.title} {e.message}" for e in events)
    for leaked in ("Rs.", "kg", "drunk", "ACKNOWLEDGE", "ADDITIONAL", "Wallet"):
        assert leaked not in blob


def test_failed_attempt_reasons_get_friendly_text() -> None:
    events = build_public_timeline(
        [
            _move(
                5,
                PickupStatus.OUT_FOR_DELIVERY,
                PickupStatus.EXCEPTION,
                ndr_raise={"reason": NdrExceptionReason.CONSIGNEE_UNAVAILABLE.value},
            )
        ]
    )
    assert (events[0].title, events[0].message) == PUBLIC_EXCEPTION_TEXT[
        NdrExceptionReason.CONSIGNEE_UNAVAILABLE
    ]


def test_consecutive_duplicates_collapse_and_unknown_values_are_ignored() -> None:
    events = build_public_timeline(
        [
            _Activity(T0, CREATION_SUMMARY),
            _move(1, PickupStatus.DRAFT, PickupStatus.OPEN),
            _Activity(T0 + timedelta(minutes=2), "x", {"status": {"old": "A", "new": "NOT_A_STATUS"}}),
            _move(3, PickupStatus.OPEN, PickupStatus.DRAFT),
        ]
    )
    assert [event.title for event in events] == ["Order placed"]


def test_every_non_draft_status_has_public_text() -> None:
    for status in PickupStatus:
        if status == PickupStatus.DRAFT:
            assert status not in PUBLIC_STATUS_TEXT
        else:
            title, message = PUBLIC_STATUS_TEXT[status]
            assert title and message
            assert "_" not in title


def test_pod_receiver_name_is_masked_to_initials() -> None:
    assert mask_person_name("Rahul Sharma") == "R*** S***"
    assert mask_person_name("  vikramaditya mehta (Dock 14) ") == "V*** M*** D*** 1***"
    assert mask_person_name("Consignee") == "C***"


def test_blank_receiver_name_is_dropped() -> None:
    for blank in (None, "", "   ", "()-."):
        assert mask_person_name(blank) is None
