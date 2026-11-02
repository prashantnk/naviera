from typing import Dict, FrozenSet, List, Set

from fastapi import HTTPException, status
from app.models.pickups import PickupStatus

class ShipmentLifecycleMachine:
    """
    State machine for shipment lifecycles, implementing Phase C rules (H-6).
    """

    # H-6 terminal states. Nothing leaves these.
    TERMINAL_STATUSES: Set[PickupStatus] = {
        PickupStatus.COMPLETED,
        PickupStatus.RTO_DELIVERED,
        PickupStatus.CANCELLED,
        PickupStatus.QC_FAILED,
        PickupStatus.REJECTED_AT_PICKUP,
    }

    # H-6: no RTO status may become COMPLETED
    RTO_STATUSES: Set[PickupStatus] = {
        PickupStatus.RTO_INITIATED,
        PickupStatus.RTO_IN_TRANSIT,
        PickupStatus.RTO_DELIVERED,
    }

    # Allowed outgoing transitions from each status (terminal statuses have none).
    ALLOWED_TRANSITIONS: Dict[PickupStatus, FrozenSet[PickupStatus]] = {
        PickupStatus.DRAFT: frozenset({PickupStatus.OPEN, PickupStatus.CANCELLED}),
        PickupStatus.OPEN: frozenset(
            {
                PickupStatus.ASSIGNED,
                PickupStatus.CANCELLED,
                PickupStatus.QC_FAILED,
                PickupStatus.REJECTED_AT_PICKUP,
            }
        ),
        PickupStatus.ASSIGNED: frozenset(
            {
                PickupStatus.IN_TRANSIT,
                PickupStatus.CANCELLED,
                PickupStatus.EXCEPTION,
                PickupStatus.QC_FAILED,
                PickupStatus.REJECTED_AT_PICKUP,
            }
        ),
        PickupStatus.IN_TRANSIT: frozenset(
            {
                PickupStatus.OUT_FOR_DELIVERY,
                PickupStatus.COMPLETED,  # Lenient
                PickupStatus.RTO_INITIATED,
                PickupStatus.EXCEPTION,
                PickupStatus.LOST,
            }
        ),
        PickupStatus.OUT_FOR_DELIVERY: frozenset(
            {
                PickupStatus.COMPLETED,
                PickupStatus.RTO_INITIATED,
                PickupStatus.EXCEPTION,
                PickupStatus.LOST,
            }
        ),
        PickupStatus.EXCEPTION: frozenset(
            {
                # Resume to the stage it was held from (D-04): before pickup, in transit,
                # out for delivery or the RTO leg; or the forced RTO / cancel / LOST.
                PickupStatus.OPEN,
                PickupStatus.ASSIGNED,
                PickupStatus.IN_TRANSIT,
                PickupStatus.OUT_FOR_DELIVERY,
                PickupStatus.RTO_INITIATED,
                PickupStatus.RTO_IN_TRANSIT,
                PickupStatus.CANCELLED,  # Pre-pickup exceptions limit hit -> CANCELLED
                PickupStatus.LOST,
            }
        ),
        PickupStatus.RTO_INITIATED: frozenset(
            {
                PickupStatus.RTO_IN_TRANSIT,
                PickupStatus.RTO_DELIVERED,  # Lenient
                PickupStatus.EXCEPTION,
                PickupStatus.LOST,
            }
        ),
        PickupStatus.RTO_IN_TRANSIT: frozenset(
            {
                PickupStatus.RTO_DELIVERED,
                PickupStatus.EXCEPTION,
                PickupStatus.LOST,
            }
        ),
        PickupStatus.LOST: frozenset(
            {
                PickupStatus.IN_TRANSIT,
                PickupStatus.RTO_INITIATED,
            }
        ),
    }

    @classmethod
    def allowed_next_statuses(cls, current: PickupStatus) -> List[PickupStatus]:
        """
        Every status `current` may move to, in enum declaration order (E-11: the status
        dialog offers only moves the server accepts).

        Args:
            current: The shipment's current status.

        Returns:
            The allowed next statuses (empty for terminal statuses).
        """
        if current in cls.TERMINAL_STATUSES:
            return []
        allowed = cls.ALLOWED_TRANSITIONS.get(current, frozenset())
        return [candidate for candidate in PickupStatus if candidate in allowed]

    @classmethod
    def validate_transition(cls, current: PickupStatus, new_status: PickupStatus) -> None:
        """
        Validates whether a transition from `current` to `new_status` is allowed.
        Raises HTTPException(400) if invalid.
        """
        if current == new_status:
            return

        if current in cls.TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid transition: Cannot move out of terminal status {current.value}",
            )

        if current in cls.RTO_STATUSES and new_status == PickupStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid transition: RTO status cannot transition to COMPLETED",
            )

        if new_status not in cls.ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status transition: Cannot move from {current.value} to {new_status.value}",
            )
