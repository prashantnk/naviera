"""Real-PostgreSQL temporal hooks scenario harness (`logismart-test` ONLY).

Seeds 11 positive + negative control shipments on `logismart-test`, verifies that no
other tenant has matching rows, runs `run_temporal_hooks_iteration()` (or `POST
/api/v1/internal/temporal-hooks/run` when `--prod` is set) twice to verify holds and
idempotency, checks `GET /api/v1/exceptions`, resolves 2 held rows and runs a 3rd
iteration to confirm resolved shipments are not re-held, and cleans up all seeded rows.

Usage (from `backend/`):
    poetry run python -m scripts.qa.cron_scenario_check --all
    poetry run python -m scripts.qa.cron_scenario_check --seed --run --api --resolve --cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

import app.main  # noqa: F401  (ensures service/model import order)
from app.core.db import AsyncSessionLocal
from app.models.pickups import (
    Address,
    NdrExceptionReason,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ProductCategory,
    ServiceType,
    ShipmentActivity,
    ShipmentType,
)
from app.models.tenants import Tenant, User
from app.schemas.v1.pickups import EWAY_BILL_MANDATORY_THRESHOLD
from scripts import temporal_hooks_worker as worker
from scripts.golden_checks import assert_live_tenants_untouched, snapshot_other_tenants
from scripts.tenant_data_core import assert_test_tenant_slug
from scripts.tests.golden_journeys.golden_env import mint_jwt

DEFAULT_SLUG = "logismart-test"
OWNER_EMAIL = "owner@logismart.in"
TAG = "QA-CRON-SCENARIO"
UTC = timezone.utc

# name -> (status, b2b, appointment_end offset, updated_at age, goods value, eway numbers, expected_reason)
SCENARIOS: dict[
    str,
    tuple[
        PickupStatus,
        bool,
        timedelta | None,
        timedelta,
        float,
        list[str] | None,
        NdrExceptionReason | None,
    ],
] = {
    "A_appt_in_transit_b2b": (
        PickupStatus.IN_TRANSIT,
        True,
        -timedelta(hours=1),
        timedelta(hours=1),
        10000.0,
        None,
        NdrExceptionReason.APPOINTMENT_NEEDED,
    ),
    "B_appt_ofd_b2c": (
        PickupStatus.OUT_FOR_DELIVERY,
        False,
        -timedelta(minutes=10),
        timedelta(hours=1),
        10000.0,
        None,
        NdrExceptionReason.APPOINTMENT_NEEDED,
    ),
    "C_eway_numbers_b2b": (
        PickupStatus.IN_TRANSIT,
        True,
        None,
        timedelta(hours=73),
        60000.0,
        ["123456789012"],
        NdrExceptionReason.EWAY_BILL_MISSING,
    ),
    "D_eway_document_b2c": (
        PickupStatus.IN_TRANSIT,
        False,
        None,
        timedelta(hours=73),
        75000.0,
        None,
        NdrExceptionReason.EWAY_BILL_MISSING,
    ),
    "N1_completed": (
        PickupStatus.COMPLETED,
        True,
        -timedelta(hours=5),
        timedelta(days=10),
        100000.0,
        ["111111111111"],
        None,
    ),
    "N2_rto_in_transit": (
        PickupStatus.RTO_IN_TRANSIT,
        True,
        -timedelta(hours=5),
        timedelta(days=10),
        100000.0,
        ["222222222222"],
        None,
    ),
    "N3_fresh_71h": (
        PickupStatus.IN_TRANSIT,
        False,
        None,
        timedelta(hours=71),
        100000.0,
        ["333333333333"],
        None,
    ),
    "N4_low_value_stale": (
        PickupStatus.IN_TRANSIT,
        False,
        None,
        timedelta(hours=100),
        float(EWAY_BILL_MANDATORY_THRESHOLD) - 0.01,
        ["444444444444"],
        None,
    ),
    "N5_json_null_low_value_stale": (
        PickupStatus.IN_TRANSIT,
        False,
        None,
        timedelta(days=9),
        20000.0,
        None,
        None,
    ),
    "N6_future_appt": (
        PickupStatus.IN_TRANSIT,
        True,
        timedelta(hours=3),
        timedelta(hours=1),
        10000.0,
        None,
        None,
    ),
    "N7_pre_pickup_appt": (
        PickupStatus.ASSIGNED,
        True,
        -timedelta(hours=2),
        timedelta(hours=1),
        10000.0,
        None,
        None,
    ),
}

RESOLVE_ACTIONS: dict[str, dict[str, str]] = {
    "C_eway_numbers_b2b": {
        "action": "UPDATE_EWAY_BILL",
        "eway_bill_number": "555566667777",
        "notes": TAG,
    },
    "A_appt_in_transit_b2b": {
        "action": "DELIVER_WITHOUT_APPOINTMENT",
        "notes": TAG,
    },
}


def _now() -> datetime:
    return datetime.now(UTC)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


async def _tenant_and_owner(session, slug: str) -> tuple[Tenant, User]:
    assert_test_tenant_slug(slug)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one()
    owner = (
        await session.execute(
            select(User).where(User.tenant_id == tenant.id, User.email == OWNER_EMAIL)
        )
    ).scalar_one()
    return tenant, owner


def _query_filters(now: datetime):
    appt = (
        PickupRequest.appointment_end < now,
        PickupRequest.status.in_(list(worker.APPOINTMENT_CHECK_STATUSES)),
    )
    eway = (
        PickupRequest.updated_at < _naive(now) - worker.EWAY_BILL_STALE_AFTER,
        PickupRequest.status == PickupStatus.IN_TRANSIT,
        PaymentDetails.shipment_total_value >= EWAY_BILL_MANDATORY_THRESHOLD,
    )
    return appt, eway


async def _matches_by_tenant(session) -> dict[str, dict[str, int]]:
    now = _now()
    appt, eway = _query_filters(now)
    out: dict[str, dict[str, int]] = {}
    appt_rows = (
        await session.execute(
            select(Tenant.slug, func.count())
            .select_from(PickupRequest)
            .join(Tenant, Tenant.id == PickupRequest.tenant_id)
            .where(*appt)
            .group_by(Tenant.slug)
        )
    ).all()
    out["appointments"] = dict(appt_rows)
    eway_rows = (
        await session.execute(
            select(Tenant.slug, func.count())
            .select_from(PickupRequest)
            .join(PaymentDetails)
            .join(Tenant, Tenant.id == PickupRequest.tenant_id)
            .where(*eway)
            .group_by(Tenant.slug)
        )
    ).all()
    out["eway"] = dict(eway_rows)
    return out


async def _worker_activity_count_outside_test(
    session, slug: str, since: datetime
) -> int:
    tenant, _ = await _tenant_and_owner(session, slug)
    return (
        await session.execute(
            select(func.count())
            .select_from(ShipmentActivity)
            .join(PickupRequest)
            .where(
                PickupRequest.tenant_id != tenant.id,
                ShipmentActivity.timestamp >= _naive(since),
                ShipmentActivity.summary.in_(
                    [
                        worker.APPOINTMENT_EXPIRED_SUMMARY,
                        worker.EWAY_BILL_STALE_SUMMARY,
                    ]
                ),
            )
        )
    ).scalar_one()


async def seed_scenarios(slug: str, state_path: Path) -> None:
    assert_test_tenant_slug(slug)
    async with AsyncSessionLocal() as session:
        tenant, owner = await _tenant_and_owner(session, slug)
        address = Address(
            name=f"{TAG} Consignee",
            phone="9999999999",
            address_line1="QA cron lane",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
            tenant_id=tenant.id,
            user_id=owner.id,
        )
        session.add(address)
        await session.flush()
        ids: dict[str, object] = {"address": str(address.id), "shipments": {}}
        shipments_map: dict[str, str] = {}
        now = _now()
        for name, (status, b2b, appt, age, value, ewb, _) in SCENARIOS.items():
            req = PickupRequest(
                tenant_id=tenant.id,
                created_by_user_id=owner.id,
                status=status,
                product_category=(
                    ProductCategory.COMMERCIAL if b2b else ProductCategory.ELECTRONICS
                ),
                po_number=f"{TAG}-{name}" if b2b else None,
                appointment_end=(now + appt) if appt is not None else None,
                appointment_start=(
                    (now + appt - timedelta(hours=2)) if appt is not None else None
                ),
                requested_pickup_date=now.date(),
                pickup_address_id=address.id,
                delivery_address_id=address.id,
                shipment_type=ShipmentType.FORWARD,
                service_type=ServiceType.SURFACE_ROAD,
                ndr_remark=f"{TAG} seed {name}",
                created_at=_naive(now - age),
                updated_at=_naive(now - age),
            )
            session.add(req)
            await session.flush()
            session.add(
                PaymentDetails(
                    pickup_id=req.id,
                    shipment_value=value,
                    shipment_total_value=value,
                    eway_bill_numbers=ewb,
                )
            )
            shipments_map[name] = str(req.id)
        ids["shipments"] = shipments_map
        await session.commit()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(ids, indent=2))
    print(f"seeded {len(shipments_map)} rows -> {state_path}")


def _trigger_http(api_url: str, cron_secret: str) -> dict[str, int]:
    endpoint = f"{api_url.rstrip('/')}/internal/temporal-hooks/run"
    req = urllib.request.Request(
        endpoint,
        data=b"",
        method="POST",
        headers={"X-Cron-Secret": cron_secret},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.load(resp)
    print("http trigger ->", resp.status, body)
    return {k: int(body[k]) for k in ("appointments_held", "eway_bills_held")}


async def run_and_verify(
    slug: str,
    state_path: Path,
    *,
    use_http: bool = False,
    api_url: str = "",
    cron_secret: str = "",
) -> list[str]:
    assert_test_tenant_slug(slug)
    ids: dict[str, str] = json.loads(state_path.read_text())["shipments"]
    async with AsyncSessionLocal() as session:
        matches = await _matches_by_tenant(session)
        print("pre-run query matches by tenant:", matches)
        others = {
            k: {s: n for s, n in v.items() if s != slug} for k, v in matches.items()
        }
        if any(others.values()):
            raise RuntimeError(f"ABORT: live-tenant rows match queries: {others}")
        await session.rollback()

    started = _now()
    if use_http:
        first = _trigger_http(api_url, cron_secret)
        second = _trigger_http(api_url, cron_secret)
    else:
        first = await worker.run_temporal_hooks_iteration()
        second = await worker.run_temporal_hooks_iteration()
    print("run 1:", first, "| run 2 (idempotency):", second)

    failures: list[str] = []
    async with AsyncSessionLocal() as session:
        _, owner = await _tenant_and_owner(session, slug)
        for name, sid in ids.items():
            req = await session.get(PickupRequest, uuid.UUID(sid))
            assert req is not None
            status0, *_rest, expected = SCENARIOS[name]
            acts = (
                (
                    await session.execute(
                        select(ShipmentActivity).where(
                            ShipmentActivity.pickup_id == req.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if expected is None:
                ok = req.status == status0 and not acts
                detail = f"status={req.status.value} activities={len(acts)}"
            else:
                act = acts[0] if len(acts) == 1 else None
                ok = (
                    req.status == PickupStatus.EXCEPTION
                    and req.ndr_reason == expected
                    and req.exception_raised_at is not None
                    and req.exception_raised_at.tzinfo is None
                    and req.ndr_remark
                    in (
                        worker.APPOINTMENT_EXPIRED_REMARK,
                        worker.EWAY_BILL_STALE_REMARK,
                    )
                    and act is not None
                    and act.is_public
                    and act.user_id == owner.id
                    and act.diff["ndr_raise"]["held_from"] == status0.value
                    and act.diff["ndr_raise"]["source"] == worker.WORKER_SOURCE
                    and act.diff["status"]
                    == {"old": status0.value, "new": "EXCEPTION"}
                )
                held_from = act.diff["ndr_raise"]["held_from"] if act else None
                detail = (
                    f"status={req.status.value} "
                    f"reason={getattr(req.ndr_reason, 'value', None)} "
                    f"activities={len(acts)} held_from={held_from}"
                )
            print(("PASS " if ok else "FAIL ") + name.ljust(30), detail)
            if not ok:
                failures.append(name)
        leaked = await _worker_activity_count_outside_test(session, slug, started)
        print("worker activities written outside test tenant during run:", leaked)
        if leaked:
            failures.append("live-tenant-leak")
        await session.rollback()

    if second != {"appointments_held": 0, "eway_bills_held": 0}:
        failures.append("idempotency")
    print("RUN RESULT:", "PASS" if not failures else f"FAIL {failures}")
    return failures


async def verify_exceptions_api(slug: str, state_path: Path, api_url: str) -> list[str]:
    assert_test_tenant_slug(slug)
    async with AsyncSessionLocal() as session:
        _, owner = await _tenant_and_owner(session, slug)
        token = mint_jwt(owner.supabase_user_id, owner.email)
        await session.rollback()
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-Slug": slug}
    ids = {v: k for k, v in json.loads(state_path.read_text())["shipments"].items()}
    failures: list[str] = []
    for flow in ("B2B", "B2C"):
        url = f"{api_url.rstrip('/')}/exceptions?service_flow={flow}&size=100"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.load(resp)
        mine = [r for r in body["items"] if r["shipment_id"] in ids]
        print(
            f"{flow}: total on hold={body['total']} seeded rows visible={len(mine)}"
        )
        if len(mine) != 2:
            failures.append(f"exceptions_api_{flow}_count_{len(mine)}")
        for row in mine:
            print(
                f"   {ids[row['shipment_id']]:<24} flow={row['service_flow']} "
                f"reason={row['ndr_reason']} category={row['category']} "
                f"actionable={row['is_actionable']} actions={row['allowed_actions']}"
            )
    return failures


async def resolve_and_recheck(
    slug: str,
    state_path: Path,
    api_url: str,
    *,
    use_http: bool = False,
    cron_secret: str = "",
) -> list[str]:
    assert_test_tenant_slug(slug)
    ids: dict[str, str] = json.loads(state_path.read_text())["shipments"]
    async with AsyncSessionLocal() as session:
        _, owner = await _tenant_and_owner(session, slug)
        token = mint_jwt(owner.supabase_user_id, owner.email)
        await session.rollback()

    failures: list[str] = []
    for name, payload in RESOLVE_ACTIONS.items():
        req = urllib.request.Request(
            f"{api_url.rstrip('/')}/exceptions/{ids[name]}/actions",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-Slug": slug,
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                row = json.load(resp)
            print(name, payload["action"], "->", resp.status, "status", row["status"])
            if row["status"] != "IN_TRANSIT":
                failures.append(f"resolve_{name}_status_{row['status']}")
        except urllib.error.HTTPError as exc:
            print(name, payload["action"], "-> HTTP", exc.code)
            failures.append(f"resolve_{name}_http_{exc.code}")

    third = (
        _trigger_http(api_url, cron_secret)
        if use_http
        else await worker.run_temporal_hooks_iteration()
    )
    print("worker after resolution (run 3):", third)
    if third != {"appointments_held": 0, "eway_bills_held": 0}:
        failures.append(f"reheld_after_resolve_{third}")
    return failures


async def cleanup_scenarios(slug: str, state_path: Path) -> None:
    assert_test_tenant_slug(slug)
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text())
    sids = [uuid.UUID(s) for s in state["shipments"].values()]
    async with AsyncSessionLocal() as session:
        tenant, _ = await _tenant_and_owner(session, slug)
        owned = (
            await session.execute(
                select(func.count())
                .select_from(PickupRequest)
                .where(
                    PickupRequest.id.in_(sids),
                    PickupRequest.tenant_id == tenant.id,
                )
            )
        ).scalar_one()
        assert owned == len(sids), "refusing: some ids do not belong to test tenant"
        await session.execute(
            delete(ShipmentActivity).where(ShipmentActivity.pickup_id.in_(sids))
        )
        await session.execute(
            delete(PaymentDetails).where(PaymentDetails.pickup_id.in_(sids))
        )
        await session.execute(
            delete(PickupRequest).where(
                PickupRequest.id.in_(sids), PickupRequest.tenant_id == tenant.id
            )
        )
        await session.execute(
            delete(Address).where(
                Address.id == uuid.UUID(state["address"]),
                Address.tenant_id == tenant.id,
            )
        )
        await session.commit()
    state_path.unlink(missing_ok=True)
    print(f"cleaned up {len(sids)} shipments + address")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default=DEFAULT_SLUG, help="Test tenant slug")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("QA_API_URL", "http://localhost:8000/api/v1"),
        help="Base API v1 URL",
    )
    parser.add_argument(
        "--state-file",
        default=os.environ.get(
            "QA_CRON_STATE_FILE", "/tmp/naviera_qa_cron_state.json"
        ),
        help="Path to temporary state JSON",
    )
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Trigger via HTTP POST /internal/temporal-hooks/run using CRON_SECRET",
    )
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--api", action="store_true")
    parser.add_argument("--resolve", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run seed -> run -> api -> resolve -> cleanup with live-tenant guard",
    )
    return parser.parse_args()


async def _async_main() -> int:
    args = _parse_args()
    assert_test_tenant_slug(args.tenant)
    state_path = Path(args.state_file)
    cron_secret = os.environ.get("CRON_SECRET", "").strip()
    if args.prod and not cron_secret:
        raise RuntimeError("--prod requires CRON_SECRET in environment")

    if args.all:
        before = await snapshot_other_tenants(args.tenant)
        failures: list[str] = []
        try:
            await seed_scenarios(args.tenant, state_path)
            failures.extend(
                await run_and_verify(
                    args.tenant,
                    state_path,
                    use_http=args.prod,
                    api_url=args.api_url,
                    cron_secret=cron_secret,
                )
            )
            failures.extend(
                await verify_exceptions_api(args.tenant, state_path, args.api_url)
            )
            failures.extend(
                await resolve_and_recheck(
                    args.tenant,
                    state_path,
                    args.api_url,
                    use_http=args.prod,
                    cron_secret=cron_secret,
                )
            )
        finally:
            await cleanup_scenarios(args.tenant, state_path)
        await assert_live_tenants_untouched(before, args.tenant)
        print("OVERALL:", "PASS" if not failures else f"FAIL {failures}")
        return 0 if not failures else 1

    failures = []
    if args.seed:
        await seed_scenarios(args.tenant, state_path)
    if args.run:
        failures.extend(
            await run_and_verify(
                args.tenant,
                state_path,
                use_http=args.prod,
                api_url=args.api_url,
                cron_secret=cron_secret,
            )
        )
    if args.api:
        failures.extend(
            await verify_exceptions_api(args.tenant, state_path, args.api_url)
        )
    if args.resolve:
        failures.extend(
            await resolve_and_recheck(
                args.tenant,
                state_path,
                args.api_url,
                use_http=args.prod,
                cron_secret=cron_secret,
            )
        )
    if args.cleanup:
        await cleanup_scenarios(args.tenant, state_path)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_async_main()))
