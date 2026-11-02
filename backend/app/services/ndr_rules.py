"""
Pure Delivery Exceptions / NDR rules (Delhivery One parity).

No I/O lives here: everything is a deterministic function of the NDR reason,
the shipment direction (FORWARD / REVERSE), the flow (B2C / B2B, decided by the
shared SQL classifier `b2b_shipment_clause()`) and the attempt counter. The
services call these helpers so the rules exist in exactly one place.

Spring Boot Equivalent: a stateless '@Component' policy class.
"""

from typing import Dict, FrozenSet, List, Optional, Tuple

from app.models.exceptions import ExceptionCategory
from app.models.manifests import ServiceFlow
from app.models.pickups import NdrAction, NdrExceptionReason, PickupStatus, ShipmentType
from app.models.wallet import WalletTxnType

# --- Limits -----------------------------------------------------------------

MAX_NDR_ATTEMPTS = 3
"""Failed delivery (forward) or pickup (reverse) attempts before auto-RTO / auto-cancel."""

MAX_BULK_ACTION_SHIPMENTS = 200
"""Delhivery allows bulk NDR actions on up to 200 AWBs at once."""

# --- Reason groups ----------------------------------------------------------

REASON_ALIASES: Dict[NdrExceptionReason, NdrExceptionReason] = {
    NdrExceptionReason.CUSTOMER_UNAVAILABLE: NdrExceptionReason.CONSIGNEE_UNAVAILABLE,
}

DELIVERY_ATTEMPT_REASONS: FrozenSet[NdrExceptionReason] = frozenset(
    {
        NdrExceptionReason.CONSIGNEE_REFUSED,
        NdrExceptionReason.CONSIGNEE_UNAVAILABLE,
        NdrExceptionReason.DELIVERY_RESCHEDULED,
    }
)
"""Canonical reasons that mean "the field agent attempted and failed"."""

ATTEMPT_COUNTING_REASONS: FrozenSet[NdrExceptionReason] = DELIVERY_ATTEMPT_REASONS | {
    NdrExceptionReason.PICKUP_FAILED
}
"""Raising one of these increments `ndr_attempt_count`."""

CHARGE_TXN_TYPES: Dict[NdrExceptionReason, WalletTxnType] = {
    NdrExceptionReason.FREIGHT_COLLECTION: WalletTxnType.FREIGHT_COLLECTION,
    NdrExceptionReason.ADDITIONAL_CHARGES: WalletTxnType.ADDITIONAL_CHARGE,
}
"""Reasons whose acknowledgement debits the merchant wallet by `charge_amount`."""

# --- Action groups ----------------------------------------------------------

BULK_ACTIONS: FrozenSet[NdrAction] = frozenset(
    {
        NdrAction.REATTEMPT,
        NdrAction.RETURN_TO_ORIGIN,
        NdrAction.RESCHEDULE_PICKUP,
        NdrAction.CANCEL_PICKUP,
    }
)

AWAITING_OPS_ACTIONS: FrozenSet[NdrAction] = frozenset(
    {NdrAction.HOLD, NdrAction.DISPUTE_WEIGHT}
)
"""After these the shipment stays on hold but the ball is in the ops team's court."""

ATTEMPT_RETRY_ACTIONS: FrozenSet[NdrAction] = frozenset(
    {NdrAction.REATTEMPT, NdrAction.RESCHEDULE_PICKUP}
)

WALLET_DEBIT_ACTIONS: FrozenSet[NdrAction] = frozenset(
    {NdrAction.ACKNOWLEDGE_CHARGES, NdrAction.ACCEPT_WEIGHT}
)
"""Merchant consent to a charge: only the shipment owner or owner/admin may act (D30)."""

PICKUP_STAGE_ACTIONS: Tuple[NdrAction, ...] = (
    NdrAction.RESCHEDULE_PICKUP,
    NdrAction.CANCEL_PICKUP,
)

CONSENT_ACTIONS: FrozenSet[NdrAction] = WALLET_DEBIT_ACTIONS | {
    NdrAction.RETURN_TO_ORIGIN,
    NdrAction.UPDATE_PAYMENT_MODE,
}
"""
Actions that cost the shipper money or change what the rider collects (A-22): only the
shipment's owner or a Tenant Owner/Admin may take them (D30). Operations / support staff
can never start an RTO or flip COD -> prepaid on a buyer's word.
"""

# --- Lifecycle stage (where the shipment was when the exception was raised) ---

PRE_PICKUP_STATUSES: FrozenSet[PickupStatus] = frozenset(
    {PickupStatus.DRAFT, PickupStatus.OPEN, PickupStatus.ASSIGNED}
)
"""The parcel is still with the merchant (or the reverse customer): not picked up yet."""

RTO_LEG_STATUSES: FrozenSet[PickupStatus] = frozenset(
    {PickupStatus.RTO_INITIATED, PickupStatus.RTO_IN_TRANSIT}
)
"""The parcel is already travelling back to the merchant."""

DELIVERY_RESUME_STATUSES: Dict[PickupStatus, PickupStatus] = {
    PickupStatus.IN_TRANSIT: PickupStatus.IN_TRANSIT,
    PickupStatus.OUT_FOR_DELIVERY: PickupStatus.IN_TRANSIT,
    PickupStatus.RTO_INITIATED: PickupStatus.RTO_INITIATED,
    PickupStatus.RTO_IN_TRANSIT: PickupStatus.RTO_IN_TRANSIT,
}
"""
Post-pickup status a resolved exception returns to (D-04): an RTO parcel stays on the RTO
leg, and a failed Out-for-delivery goes back to the hub (In transit) for the next run.
"""

RTO_LEG_EXCLUDED_ACTIONS: FrozenSet[NdrAction] = frozenset(
    {NdrAction.RETURN_TO_ORIGIN, NdrAction.UPDATE_PAYMENT_MODE}
)
"""Already returning (nothing is collected on the RTO leg): no RTO or payment-mode switch."""

PICKUP_FAILED_AFTER_PICKUP_DETAIL = (
    "Pickup failed can only be raised before the parcel is picked up. "
    "Choose the delivery reason instead."
)
DELIVERY_REASON_BEFORE_PICKUP_DETAIL = (
    "This parcel has not been picked up yet, so it can't have a failed delivery. "
    "Use Pickup failed instead."
)

# --- Allowed-actions matrix (forward direction) -----------------------------

_DELIVERY_ATTEMPT_B2C_ACTIONS: Tuple[NdrAction, ...] = (
    NdrAction.REATTEMPT,
    NdrAction.UPDATE_CONSIGNEE,
    NdrAction.RETURN_TO_ORIGIN,
)
_DELIVERY_ATTEMPT_B2B_ACTIONS: Tuple[NdrAction, ...] = (
    NdrAction.REATTEMPT,
    NdrAction.RETURN_TO_ORIGIN,
)

_COMMON_FORWARD_ACTIONS: Dict[NdrExceptionReason, Tuple[NdrAction, ...]] = {
    NdrExceptionReason.EWAY_BILL_MISSING: (NdrAction.UPDATE_EWAY_BILL,),
    NdrExceptionReason.DOCUMENT_NEEDED: (NdrAction.UPLOAD_DOCUMENT,),
    NdrExceptionReason.APPOINTMENT_NEEDED: (
        NdrAction.BOOK_APPOINTMENT,
        NdrAction.DELIVER_WITHOUT_APPOINTMENT,
    ),
    NdrExceptionReason.SHORT_SHIPMENT: (NdrAction.PARTIAL_DELIVERY, NdrAction.HOLD),
    NdrExceptionReason.FREIGHT_COLLECTION: (NdrAction.ACKNOWLEDGE_CHARGES,),
    NdrExceptionReason.ADDITIONAL_CHARGES: (NdrAction.ACKNOWLEDGE_CHARGES,),
    NdrExceptionReason.WEIGHT_DISCREPANCY: (
        NdrAction.ACCEPT_WEIGHT,
        NdrAction.DISPUTE_WEIGHT,
    ),
}

B2C_FORWARD_MATRIX: Dict[NdrExceptionReason, Tuple[NdrAction, ...]] = {
    **_COMMON_FORWARD_ACTIONS,
    NdrExceptionReason.DAMAGED: (NdrAction.REATTEMPT, NdrAction.RETURN_TO_ORIGIN),
    NdrExceptionReason.EWAY_BILL_MISSING: (
        NdrAction.UPDATE_EWAY_BILL,
        NdrAction.RETURN_TO_ORIGIN,
    ),
    NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED: (
        NdrAction.UPDATE_CONSIGNEE,
        NdrAction.RETURN_TO_ORIGIN,
    ),
    NdrExceptionReason.PAYMENT_DISPUTE: (
        NdrAction.UPDATE_PAYMENT_MODE,
        NdrAction.RETURN_TO_ORIGIN,
    ),
    **{reason: _DELIVERY_ATTEMPT_B2C_ACTIONS for reason in DELIVERY_ATTEMPT_REASONS},
}
"""Delhivery Domestic: Shipment Exceptions + NDR (forward)."""

B2B_FORWARD_MATRIX: Dict[NdrExceptionReason, Tuple[NdrAction, ...]] = {
    **_COMMON_FORWARD_ACTIONS,
    NdrExceptionReason.PAYMENT_DISPUTE: (
        NdrAction.UPDATE_PAYMENT_MODE,
        NdrAction.REATTEMPT,
    ),
    NdrExceptionReason.DAMAGED: (
        NdrAction.RETURN_TO_ORIGIN,
        NdrAction.REPACK_AND_DELIVER,
    ),
    NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED: (
        NdrAction.UPDATE_CONSIGNEE,
        NdrAction.REATTEMPT,
    ),
    **{reason: _DELIVERY_ATTEMPT_B2B_ACTIONS for reason in DELIVERY_ATTEMPT_REASONS},
}
"""Delhivery Cargo: the eleven "on hold" categories (forward)."""

# --- Category mapping -------------------------------------------------------

FLOW_CATEGORIES: Dict[ServiceFlow, Tuple[ExceptionCategory, ...]] = {
    ServiceFlow.B2C: (
        ExceptionCategory.SHIPMENT_EXCEPTIONS,
        ExceptionCategory.NDR,
        ExceptionCategory.PICKUP_FAILED,
        ExceptionCategory.NON_ACTIONABLE,
    ),
    ServiceFlow.B2B: (
        ExceptionCategory.PAYMENT_DISPUTE,
        ExceptionCategory.DAMAGES,
        ExceptionCategory.EWAY_BILL,
        ExceptionCategory.CONSIGNEE_DETAILS,
        ExceptionCategory.DOCUMENT_NEEDED,
        ExceptionCategory.SHORT_SHIPMENTS,
        ExceptionCategory.NDR,
        ExceptionCategory.APPOINTMENT_NEEDED,
        ExceptionCategory.FREIGHT_COLLECTION,
        ExceptionCategory.ADDITIONAL_CHARGES,
        ExceptionCategory.MEASURED_WEIGHT,
    ),
}

CATEGORY_LABELS: Dict[ExceptionCategory, str] = {
    ExceptionCategory.SHIPMENT_EXCEPTIONS: "Shipment Exceptions",
    ExceptionCategory.NDR: "NDR (Undelivered)",
    ExceptionCategory.PICKUP_FAILED: "Pickup Failed",
    ExceptionCategory.NON_ACTIONABLE: "Non-actionable",
    ExceptionCategory.PAYMENT_DISPUTE: "Payment Dispute",
    ExceptionCategory.DAMAGES: "Damages",
    ExceptionCategory.EWAY_BILL: "E-Way Bill",
    ExceptionCategory.CONSIGNEE_DETAILS: "Consignee Details Required",
    ExceptionCategory.DOCUMENT_NEEDED: "Document Needed",
    ExceptionCategory.SHORT_SHIPMENTS: "Short Shipments",
    ExceptionCategory.APPOINTMENT_NEEDED: "Appointment Needed",
    ExceptionCategory.FREIGHT_COLLECTION: "Freight Collection",
    ExceptionCategory.ADDITIONAL_CHARGES: "Additional Charges",
    ExceptionCategory.MEASURED_WEIGHT: "Acknowledge Measured Weight",
}

B2B_REASON_CATEGORIES: Dict[NdrExceptionReason, ExceptionCategory] = {
    NdrExceptionReason.PAYMENT_DISPUTE: ExceptionCategory.PAYMENT_DISPUTE,
    NdrExceptionReason.DAMAGED: ExceptionCategory.DAMAGES,
    NdrExceptionReason.EWAY_BILL_MISSING: ExceptionCategory.EWAY_BILL,
    NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED: ExceptionCategory.CONSIGNEE_DETAILS,
    NdrExceptionReason.DOCUMENT_NEEDED: ExceptionCategory.DOCUMENT_NEEDED,
    NdrExceptionReason.SHORT_SHIPMENT: ExceptionCategory.SHORT_SHIPMENTS,
    NdrExceptionReason.APPOINTMENT_NEEDED: ExceptionCategory.APPOINTMENT_NEEDED,
    NdrExceptionReason.FREIGHT_COLLECTION: ExceptionCategory.FREIGHT_COLLECTION,
    NdrExceptionReason.ADDITIONAL_CHARGES: ExceptionCategory.ADDITIONAL_CHARGES,
    NdrExceptionReason.WEIGHT_DISCREPANCY: ExceptionCategory.MEASURED_WEIGHT,
    NdrExceptionReason.PICKUP_FAILED: ExceptionCategory.NDR,
    **{reason: ExceptionCategory.NDR for reason in DELIVERY_ATTEMPT_REASONS},
}


# --- Helpers ----------------------------------------------------------------


def canonical_reason(
    reason: Optional[NdrExceptionReason],
) -> Optional[NdrExceptionReason]:
    """
    Resolves legacy aliases (CUSTOMER_UNAVAILABLE -> CONSIGNEE_UNAVAILABLE).

    Args:
        reason: The stored NDR reason (may be None for legacy rows).

    Returns:
        The canonical reason, or None.
    """
    if reason is None:
        return None
    return REASON_ALIASES.get(reason, reason)


def counts_as_attempt(reason: Optional[NdrExceptionReason]) -> bool:
    """True when raising this reason means a failed delivery / pickup attempt."""
    return canonical_reason(reason) in ATTEMPT_COUNTING_REASONS


def is_picked_up(held_from: Optional[PickupStatus]) -> bool:
    """
    True when the exception was raised after the parcel left the merchant.

    Args:
        held_from: Status the shipment had when the exception was raised (None = unknown,
            legacy rows; callers then fall back to the reason-only rules).
    """
    return held_from is not None and held_from not in PRE_PICKUP_STATUSES


def is_rto_leg(held_from: Optional[PickupStatus]) -> bool:
    """True when the exception was raised while the parcel was returning to the merchant."""
    return held_from in RTO_LEG_STATUSES


def raise_rejection(
    reason: Optional[NdrExceptionReason],
    shipment_type: ShipmentType,
    held_from: PickupStatus,
) -> Optional[str]:
    """
    Refuses reasons that contradict the parcel's stage (A-21, D-04b).

    - PICKUP_FAILED after pickup would later auto-cancel with a full refund after the
      goods moved.
    - A failed *delivery* on a forward parcel that was never picked up would resume it to
      In transit (and count an attempt towards auto-RTO) although it never left.

    Args:
        reason: The reason being raised.
        shipment_type: FORWARD or REVERSE.
        held_from: The shipment's status at the moment of the raise.

    Returns:
        A plain-English error for a 400, or None when the reason is allowed.
    """
    canonical = canonical_reason(reason)
    picked_up = is_picked_up(held_from)
    if canonical == NdrExceptionReason.PICKUP_FAILED and picked_up:
        return PICKUP_FAILED_AFTER_PICKUP_DETAIL
    if (
        not picked_up
        and shipment_type == ShipmentType.FORWARD
        and canonical in DELIVERY_ATTEMPT_REASONS
    ):
        return DELIVERY_REASON_BEFORE_PICKUP_DETAIL
    return None


def is_pickup_stage(
    reason: Optional[NdrExceptionReason],
    shipment_type: ShipmentType,
    held_from: Optional[PickupStatus] = None,
) -> bool:
    """
    True when the exception happened while collecting the parcel (NPR).

    With a known `held_from` (A-21) it is a pickup-stage exception only when the parcel
    was not yet picked up and the reason is a failed attempt. Without it (legacy rows) the
    reason decides: any PICKUP_FAILED, or a reverse shipment whose customer refused / was
    unavailable / rescheduled the pickup.

    Args:
        reason: The NDR reason.
        shipment_type: FORWARD or REVERSE.
        held_from: Status when the exception was raised (None = unknown).
    """
    canonical = canonical_reason(reason)
    if held_from is not None:
        return not is_picked_up(held_from) and canonical in ATTEMPT_COUNTING_REASONS
    if canonical == NdrExceptionReason.PICKUP_FAILED:
        return True
    return shipment_type == ShipmentType.REVERSE and canonical in DELIVERY_ATTEMPT_REASONS


def flow_of(is_b2b: bool) -> ServiceFlow:
    """Maps the shared B2B classifier result onto the ServiceFlow enum."""
    return ServiceFlow.B2B if is_b2b else ServiceFlow.B2C


def _forward_actions(
    reason: NdrExceptionReason, is_b2b: bool
) -> Tuple[NdrAction, ...]:
    """Looks up the forward-direction actions for a canonical reason and flow."""
    matrix = B2B_FORWARD_MATRIX if is_b2b else B2C_FORWARD_MATRIX
    return matrix.get(reason, ())


def _drop_actions(
    actions: Tuple[NdrAction, ...], excluded: FrozenSet[NdrAction]
) -> Tuple[NdrAction, ...]:
    """Removes `excluded` from an ordered action tuple."""
    return tuple(action for action in actions if action not in excluded)


def allowed_actions(
    reason: Optional[NdrExceptionReason],
    shipment_type: ShipmentType,
    is_b2b: bool,
    held_from: Optional[PickupStatus] = None,
) -> List[NdrAction]:
    """
    The allowed-actions matrix: reason x direction x flow x stage -> actions.

    Pickup-stage exceptions (NPR) only allow Reschedule / Cancel pickup.
    Return-to-Origin is never offered for reverse shipments (already travelling back),
    for parcels not yet picked up, or on the RTO leg (which also drops the payment-mode
    switch: nothing is collected on a return).

    Args:
        reason: The shipment's NDR reason (None -> no actions).
        shipment_type: FORWARD or REVERSE.
        is_b2b: Result of the shared `b2b_shipment_clause()` classifier.
        held_from: Status when the exception was raised (None = unknown, legacy rows).

    Returns:
        Ordered list of actions the merchant may take (empty = non-actionable).
    """
    canonical = canonical_reason(reason)
    if canonical is None:
        return []
    if is_pickup_stage(canonical, shipment_type, held_from):
        return list(PICKUP_STAGE_ACTIONS)
    actions = _forward_actions(canonical, is_b2b)
    if is_rto_leg(held_from):
        actions = _drop_actions(actions, RTO_LEG_EXCLUDED_ACTIONS)
    not_picked_up = held_from is not None and not is_picked_up(held_from)
    if shipment_type == ShipmentType.REVERSE or not_picked_up:
        actions = _drop_actions(actions, frozenset({NdrAction.RETURN_TO_ORIGIN}))
    return list(actions)


def attempt_limit_outcome(
    reason: Optional[NdrExceptionReason],
    shipment_type: ShipmentType,
    attempts: int,
    held_from: Optional[PickupStatus] = None,
) -> Optional[PickupStatus]:
    """
    Status the system forces once the attempt limit is reached.

    Forward delivery attempts -> RTO_INITIATED; pickup-stage attempts -> CANCELLED.
    Nothing is forced on the RTO leg or for a reverse parcel already picked up (it is
    being delivered back to the merchant): those stay with ops.

    Args:
        reason: The current NDR reason.
        shipment_type: FORWARD or REVERSE.
        attempts: Current `ndr_attempt_count`.
        held_from: Status when the exception was raised (None = unknown, legacy rows).

    Returns:
        The forced status, or None while attempts remain.
    """
    if not counts_as_attempt(reason) or attempts < MAX_NDR_ATTEMPTS:
        return None
    if is_rto_leg(held_from):
        return None
    if is_pickup_stage(reason, shipment_type, held_from):
        return PickupStatus.CANCELLED
    if shipment_type == ShipmentType.REVERSE:
        return None
    return PickupStatus.RTO_INITIATED


def resume_status(
    reason: Optional[NdrExceptionReason],
    shipment_type: ShipmentType,
    has_pickup_request: bool,
    held_from: Optional[PickupStatus] = None,
) -> PickupStatus:
    """
    Status a shipment returns to once the merchant resolves the exception (D-04).

    Not yet picked up -> "Ready for Pickup" (ASSIGNED) when linked to a Pickup Request,
    otherwise "Ready to Ship" (OPEN). After pickup it returns to its leg: In transit
    (also after a failed Out-for-delivery) or the RTO status it was on. Legacy rows
    without `held_from` use the reason-only rule (pickup stage -> ASSIGNED / OPEN, else
    IN_TRANSIT).

    Args:
        reason: The NDR reason being resolved.
        shipment_type: FORWARD or REVERSE.
        has_pickup_request: Whether the shipment is linked to a manifest / PUR.
        held_from: Status when the exception was raised (None = unknown).
    """
    pre_pickup_status = PickupStatus.ASSIGNED if has_pickup_request else PickupStatus.OPEN
    if held_from is None:
        if is_pickup_stage(reason, shipment_type):
            return pre_pickup_status
        return PickupStatus.IN_TRANSIT
    if not is_picked_up(held_from):
        return pre_pickup_status
    return DELIVERY_RESUME_STATUSES.get(held_from, PickupStatus.IN_TRANSIT)


def categorize(
    reason: Optional[NdrExceptionReason],
    shipment_type: ShipmentType,
    is_b2b: bool,
    is_actionable: bool,
    held_from: Optional[PickupStatus] = None,
) -> Optional[ExceptionCategory]:
    """
    Buckets an on-hold shipment into its flow's category.

    B2C: non-actionable rows go to NON_ACTIONABLE; otherwise PICKUP_FAILED
    (pickup stage), NDR (forward delivery attempts) or SHIPMENT_EXCEPTIONS.
    B2B: one of the eleven reason-driven categories (None for legacy rows
    without a reason).
    """
    canonical = canonical_reason(reason)
    if is_b2b:
        return B2B_REASON_CATEGORIES.get(canonical) if canonical else None
    if not is_actionable:
        return ExceptionCategory.NON_ACTIONABLE
    if is_pickup_stage(canonical, shipment_type, held_from):
        return ExceptionCategory.PICKUP_FAILED
    if canonical in DELIVERY_ATTEMPT_REASONS:
        return ExceptionCategory.NDR
    return ExceptionCategory.SHIPMENT_EXCEPTIONS


def b2b_category_reasons(category: ExceptionCategory) -> List[NdrExceptionReason]:
    """
    All stored reasons (aliases included) that fall into a B2B category.
    Used to push the category filter down into SQL.
    """
    return [
        reason
        for reason in NdrExceptionReason
        if B2B_REASON_CATEGORIES.get(canonical_reason(reason)) == category
    ]
