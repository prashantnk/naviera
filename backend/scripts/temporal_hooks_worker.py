"""
Temporal hooks worker: periodic, time-based shipment checks.

Triggered every 14 minutes through `POST /api/v1/internal/temporal-hooks/run`
(`app/api/v1/endpoints/internal.py`); `main()` keeps a standalone polling loop for local use.

1. Expired delivery appointments: a parcel on its way to the consignee (In transit / Out for
   delivery) whose booked appointment window has ended goes on hold with APPOINTMENT_NEEDED
   (actions: Book appointment / Deliver without appointment). Parcels not yet picked up are
   never flagged (D-04c), and "Deliver without appointment" clears the window, so the same
   expired slot is never re-flagged (D-08).
2. Stale e-way bills: an In transit parcel whose goods value needs an e-way bill
   (>= EWAY_BILL_MANDATORY_THRESHOLD, which booking enforces as numbers or an EWAY_BILL
   document) and has had no update for 72 hours goes on hold with EWAY_BILL_MISSING
   (action: Update e-way bill), since its validity has most likely lapsed.

Every hold is validated by `ShipmentLifecycleMachine`, writes a merchant-visible
STATUS_CHANGE activity carrying `ndr_raise.held_from` (where a resolved exception resumes,
D-04), and is idempotent: held rows no longer match either query.

Hardening (G-08): each check runs in its own try/rollback with a full traceback, rows locked
by a request are skipped (`SKIP LOCKED`) instead of blocking, every iteration logs a
heartbeat, and the audit actor is always a user of the shipment's own tenant.

Spring Boot Equivalent: a `@Scheduled(fixedDelay = 300_000)` component.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set

from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.pickups import (
    ActivityType,
    NdrExceptionReason,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
)
from app.models.tenants import User
from app.schemas.v1.pickups import EWAY_BILL_MANDATORY_THRESHOLD
from app.services.shipment_lifecycle import ShipmentLifecycleMachine

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BATCH_SIZE = 100
"""Rows locked and processed per transaction."""
POLL_INTERVAL_SECONDS = 300
"""Delay between iterations of the standalone `main()` loop."""
EWAY_BILL_STALE_AFTER = timedelta(hours=72)
"""An In transit parcel needing an e-way bill with no update for this long is put on hold."""
APPOINTMENT_CHECK_STATUSES = (PickupStatus.IN_TRANSIT, PickupStatus.OUT_FOR_DELIVERY)
"""Only parcels already picked up and heading to the consignee can miss an appointment."""
APPOINTMENT_EXPIRED_SUMMARY = "Appointment expired, status changed to EXCEPTION"
APPOINTMENT_EXPIRED_REMARK = "Delivery appointment window has passed; book a new appointment."
EWAY_BILL_STALE_SUMMARY = (
    "E-way bill validity lapsed (no update for 72 hours), status changed to EXCEPTION"
)
EWAY_BILL_STALE_REMARK = "No movement for 72 hours; update the e-way bill to continue."
WORKER_SOURCE = "worker"
"""`ndr_raise.source` of holds raised by this worker."""


def _utc_now_naive() -> datetime:
    """
    Current UTC time without tzinfo.

    The `pickups` timestamp columns are TIMESTAMP WITHOUT TIME ZONE; asyncpg
    rejects timezone-aware values for them (DataError), which crashed the worker
    on Postgres (SQLite tests did not catch it).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _resolve_actors(session, reqs: Iterable[PickupRequest]) -> Dict[uuid.UUID, uuid.UUID]:
    """
    Picks the audit actor for each shipment: its creator when that user still exists,
    otherwise an active user of the SAME tenant (never another tenant's user, G-08).
    When the tenant has no user left, the creator id is kept (logged as a warning).

    Args:
        session: The worker's async session.
        reqs: The shipments of the current batch.

    Returns:
        shipment id -> actor user id.
    """
    batch = list(reqs)
    creator_ids = {req.created_by_user_id for req in batch}
    existing_result = await session.execute(select(User.id).where(User.id.in_(list(creator_ids))))
    existing_ids: Set[uuid.UUID] = set(existing_result.scalars().all())

    orphan_tenants = {req.tenant_id for req in batch if req.created_by_user_id not in existing_ids}
    tenant_actor: Dict[uuid.UUID, uuid.UUID] = {}
    if orphan_tenants:
        fallback_result = await session.execute(
            select(User.id, User.tenant_id).where(
                User.tenant_id.in_(list(orphan_tenants)), User.is_active
            )
        )
        for user_id, tenant_id in fallback_result.all():
            tenant_actor.setdefault(tenant_id, user_id)

    actors: Dict[uuid.UUID, uuid.UUID] = {}
    for req in batch:
        actor = req.created_by_user_id
        if actor not in existing_ids:
            fallback = tenant_actor.get(req.tenant_id)
            if fallback is None:
                logger.warning(
                    "No active user left in tenant %s; auditing shipment %s as its creator",
                    req.tenant_id,
                    req.id,
                )
            else:
                actor = fallback
        actors[req.id] = actor
    return actors


def _put_on_hold(
    req: PickupRequest,
    reason: NdrExceptionReason,
    actor_id: uuid.UUID,
    summary: str,
    remark: str,
) -> ShipmentActivity:
    """
    Moves one shipment to EXCEPTION (validated by the lifecycle machine) and builds its
    merchant-visible audit activity. The activity records the status it was held from,
    which is where a resolved exception resumes (D-04).

    Raises:
        HTTPException(400): the transition is not allowed (the check queries only select
            statuses that may move to EXCEPTION, so this signals a programming error).
    """
    old_status = PickupStatus(req.status)
    ShipmentLifecycleMachine.validate_transition(old_status, PickupStatus.EXCEPTION)
    now = _utc_now_naive()
    req.status = PickupStatus.EXCEPTION
    req.ndr_reason = reason
    req.ndr_remark = remark
    req.charge_amount = None
    req.updated_at = now
    req.exception_raised_at = now
    return ShipmentActivity(
        pickup_id=req.id,
        user_id=actor_id,
        activity_type=ActivityType.STATUS_CHANGE,
        summary=summary,
        comment=remark,
        is_public=True,
        diff={
            "status": {"old": old_status.value, "new": PickupStatus.EXCEPTION.value},
            "ndr_raise": {
                "reason": reason.value,
                "attempt": req.ndr_attempt_count,
                "remark": remark,
                "held_from": old_status.value,
                "source": WORKER_SOURCE,
            },
        },
    )


async def _hold_in_batches(
    session, statement, reason: NdrExceptionReason, summary: str, remark: str
) -> int:
    """
    Repeatedly locks one batch matching `statement`, puts every row on hold and commits.
    Held rows no longer match, so the loop ends when a batch comes back empty.

    Returns:
        Number of shipments put on hold.
    """
    count = 0
    while True:
        result = await session.execute(statement)
        reqs: List[PickupRequest] = list(result.scalars().all())
        if not reqs:
            break
        actors = await _resolve_actors(session, reqs)
        for req in reqs:
            session.add(_put_on_hold(req, reason, actors[req.id], summary, remark))
            count += 1
        await session.commit()
        session.expunge_all()
    return count


async def check_appointments(session) -> int:
    """Puts In transit / Out for delivery parcels with an expired appointment on hold."""
    # `appointment_end` is TIMESTAMP WITH TIME ZONE: compare with an aware instant (asyncpg
    # would read a naive value in the server process's local zone).
    statement = (
        select(PickupRequest)
        .where(
            PickupRequest.appointment_end < datetime.now(timezone.utc),
            PickupRequest.status.in_(list(APPOINTMENT_CHECK_STATUSES)),
        )
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    return await _hold_in_batches(
        session,
        statement,
        NdrExceptionReason.APPOINTMENT_NEEDED,
        APPOINTMENT_EXPIRED_SUMMARY,
        APPOINTMENT_EXPIRED_REMARK,
    )


async def check_eway_bills(session) -> int:
    """
    Puts In transit parcels worth >= the e-way bill threshold with no update for 72 hours
    on hold. Goods value (not `eway_bill_numbers`) decides: booking accepts the e-way bill
    as numbers or as an uploaded EWAY_BILL document, and most rows store JSON `null`.
    """
    stale_before = _utc_now_naive() - EWAY_BILL_STALE_AFTER
    statement = (
        select(PickupRequest)
        .join(PaymentDetails)
        .where(
            PickupRequest.updated_at < stale_before,
            PickupRequest.status == PickupStatus.IN_TRANSIT,
            PaymentDetails.shipment_total_value >= EWAY_BILL_MANDATORY_THRESHOLD,
        )
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True, of=PickupRequest)
    )
    return await _hold_in_batches(
        session,
        statement,
        NdrExceptionReason.EWAY_BILL_MISSING,
        EWAY_BILL_STALE_SUMMARY,
        EWAY_BILL_STALE_REMARK,
    )


async def _run_check(session, name: str, check) -> Optional[int]:
    """
    Runs one check in isolation: a failure is logged with its traceback and rolled back,
    and never stops the other check (G-08).

    Returns:
        The number of shipments put on hold, or None when the check failed.
    """
    try:
        return await check(session)
    except Exception:  # noqa: BLE001 - the worker must survive any single failure
        logger.exception("Temporal hook %s failed; rolled back", name)
        await session.rollback()
        return None


async def run_temporal_hooks_iteration() -> Dict[str, Optional[int]]:
    """One pass over both checks, followed by a heartbeat log line."""
    async with AsyncSessionLocal() as session:
        appointments = await _run_check(session, "check_appointments", check_appointments)
        eway_bills = await _run_check(session, "check_eway_bills", check_eway_bills)
    logger.info(
        "Temporal hooks heartbeat: appointments_held=%s eway_bills_held=%s",
        appointments,
        eway_bills,
    )
    return {
        "appointments_held": appointments,
        "eway_bills_held": eway_bills,
    }


async def main() -> None:
    """Runs forever, one iteration every POLL_INTERVAL_SECONDS."""
    logger.info("Starting temporal hooks worker...")
    while True:
        await run_temporal_hooks_iteration()
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
