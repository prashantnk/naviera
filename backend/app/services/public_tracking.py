"""
Public tracking timeline (B-03, F-01): what anyone holding a tracking link may see.

The public page is reachable by anyone the link is forwarded to (WhatsApp, email), so it is
built ONLY from an allow-list of status milestones with fixed, customer-friendly wording
(Delhivery One style). No free text (seller notes, rider remarks), no money, no weights,
no NDR action codes and no package contents ever reach it.

Pure module: no I/O, so the rules are unit-tested without a database.
Spring Boot Equivalent: a stateless `@Component` mapper from audit rows to a public DTO.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple

from app.models.pickups import NdrExceptionReason, PickupStatus

CREATION_SUMMARY = "Shipment Created"
"""Summary of the booking activity (written once at creation)."""

ORDER_PLACED_TEXT: Tuple[str, str] = (
    "Order placed",
    "The seller has booked this shipment.",
)

PUBLIC_STATUS_TEXT: Dict[PickupStatus, Tuple[str, str]] = {
    PickupStatus.OPEN: ORDER_PLACED_TEXT,
    PickupStatus.ASSIGNED: ("Pickup scheduled", "A pickup has been scheduled from the seller."),
    PickupStatus.IN_TRANSIT: ("In transit", "Your shipment has been picked up and is on its way."),
    PickupStatus.OUT_FOR_DELIVERY: ("Out for delivery", "Our delivery agent is on the way to you."),
    PickupStatus.COMPLETED: ("Delivered", "Your shipment has been delivered."),
    PickupStatus.EXCEPTION: (
        "Shipment on hold",
        "We are resolving an issue with this shipment. It will move again soon.",
    ),
    PickupStatus.RTO_INITIATED: ("Return to seller started", "This shipment is being returned to the seller."),
    PickupStatus.RTO_IN_TRANSIT: ("Return in transit", "This shipment is on its way back to the seller."),
    PickupStatus.RTO_DELIVERED: ("Returned to seller", "This shipment has been returned to the seller."),
    PickupStatus.CANCELLED: ("Cancelled", "This shipment was cancelled."),
    PickupStatus.LOST: ("Under investigation", "Please contact the seller for an update on this shipment."),
    PickupStatus.QC_FAILED: ("Pickup not completed", "The return pickup could not be completed."),
    PickupStatus.REJECTED_AT_PICKUP: ("Pickup not completed", "The return pickup could not be completed."),
}
"""Allow-listed milestones. DRAFT is never public."""

PUBLIC_EXCEPTION_TEXT: Dict[NdrExceptionReason, Tuple[str, str]] = {
    NdrExceptionReason.CONSIGNEE_UNAVAILABLE: (
        "Delivery attempted",
        "We could not reach you. We will try again.",
    ),
    NdrExceptionReason.CUSTOMER_UNAVAILABLE: (
        "Delivery attempted",
        "We could not reach you. We will try again.",
    ),
    NdrExceptionReason.CONSIGNEE_REFUSED: (
        "Delivery attempted",
        "The shipment was not accepted at delivery.",
    ),
    NdrExceptionReason.DELIVERY_RESCHEDULED: (
        "Delivery rescheduled",
        "Delivery has been rescheduled as requested.",
    ),
}
"""Failed-attempt reasons a recipient may see; every other hold shows the generic text."""


class ActivityLike(Protocol):
    """The audit fields the public timeline reads (a `ShipmentActivity`)."""

    timestamp: datetime
    summary: str
    diff: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class PublicEvent:
    """One public milestone."""

    timestamp: datetime
    title: str
    message: str


def _status_moved_to(diff: Optional[Dict[str, Any]]) -> Optional[PickupStatus]:
    """The status an activity moved the shipment INTO, or None for non-status activities."""
    status_entry = (diff or {}).get("status")
    raw = status_entry.get("new") if isinstance(status_entry, dict) else None
    try:
        return PickupStatus(raw) if raw else None
    except ValueError:
        return None


def _exception_reason(diff: Optional[Dict[str, Any]]) -> Optional[NdrExceptionReason]:
    """The NDR reason recorded on an exception raise (`ndr_raise.reason` or `ndr_reason.new`)."""
    data = diff or {}
    raise_entry = data.get("ndr_raise")
    reason_entry = data.get("ndr_reason")
    raw = (raise_entry or {}).get("reason") if isinstance(raise_entry, dict) else None
    if raw is None and isinstance(reason_entry, dict):
        raw = reason_entry.get("new")
    try:
        return NdrExceptionReason(raw) if raw else None
    except ValueError:
        return None


def _event_text(activity: ActivityLike) -> Optional[Tuple[str, str]]:
    """Fixed (title, message) for an allow-listed activity, else None (not public)."""
    if activity.summary == CREATION_SUMMARY:
        return ORDER_PLACED_TEXT
    moved_to = _status_moved_to(activity.diff)
    if moved_to is None:
        return None
    if moved_to == PickupStatus.EXCEPTION:
        reason = _exception_reason(activity.diff)
        if reason in PUBLIC_EXCEPTION_TEXT:
            return PUBLIC_EXCEPTION_TEXT[reason]
    if moved_to == PickupStatus.COMPLETED and "OTP Verified" in (activity.summary or ""):
        return ("Delivered — OTP Verified", "Your shipment has been delivered.")
    return PUBLIC_STATUS_TEXT.get(moved_to)


NAME_MASK = "***"
"""Replaces every character of a name word after its initial (fixed width: hides the length)."""


def mask_person_name(name: Optional[str]) -> Optional[str]:
    """
    Masks a person's name for the public tracking page: each word keeps only its initial
    ("Rahul Sharma (Dock 14)" -> "R*** S*** D*** 1***"). Anyone holding the link sees that
    somebody signed for the parcel, never who.

    Args:
        name: The receiver name captured at proof of delivery (may be blank).

    Returns:
        The masked name, or None when there is no name.
    """
    words = "".join(char if char.isalnum() else " " for char in (name or "")).split()
    if not words:
        return None
    return " ".join(f"{word[0].upper()}{NAME_MASK}" for word in words)


def build_public_timeline(activities: Iterable[ActivityLike]) -> List[PublicEvent]:
    """
    Maps the audit ledger onto the public milestones, oldest first, dropping every
    non-allow-listed activity and consecutive duplicates (e.g. "Order placed" from both the
    creation row and an OPEN status row).

    Args:
        activities: The shipment's activities (any order).

    Returns:
        The public events in chronological order.
    """
    events: List[PublicEvent] = []
    for activity in sorted(activities, key=lambda item: item.timestamp):
        text = _event_text(activity)
        if text is None:
            continue
        title, message = text
        if events and events[-1].title == title and events[-1].message == message:
            continue
        events.append(PublicEvent(timestamp=activity.timestamp, title=title, message=message))
    return events
