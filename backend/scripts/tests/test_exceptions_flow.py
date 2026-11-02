"""
Delivery Exceptions / NDR flow (Phase O.8, X1).

Covers the allowed-actions matrix, attempt limits (auto-RTO / auto-cancel),
same-pincode address edits, customer scoping, charge acknowledgement with
Finlock, bulk actions, summary counts and the legacy resolve-exception API.
All writes happen inside the per-test transaction from conftest (rolled back).
"""

import uuid
from datetime import date, timedelta
from typing import Optional

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.main import app
from app.models.exceptions import ExceptionCategory
from app.models.manifests import ServiceFlow
from app.models.pickups import (
    NdrAction,
    NdrExceptionReason,
    PickupRequest,
    PickupStatus,
    ShipmentType,
)
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.models.wallet import UserWallet, WalletTransaction, WalletTxnType
from app.services import ndr_rules

HEADERS = {"X-Tenant-Slug": "naviera"}
SHIPMENTS_URL = f"{settings.API_V1_STR}/shipments"
EXCEPTIONS_URL = f"{settings.API_V1_STR}/exceptions"
B2C_DELIVERY_PINCODE = "400001"


# --------------------------------------------------------------------------- helpers


def _shipment_payload(
    *, b2b: bool = False, reverse: bool = False, total_value: float = 1000.0
) -> dict:
    """Minimal valid booking; B2B is flagged through carrier's risk (shared classifier)."""
    tag = uuid.uuid4().hex[:8]
    payload = {
        "order_reference_id": f"NDR-{tag}",
        "shipment_type": "REVERSE" if reverse else "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "pickup_time_slot": "10:00 - 14:00",
        "product_category": "ELECTRONICS",
        "is_carriers_risk": b2b,
        "new_pickup_address": {
            "name": f"NDR Origin {tag}",
            "phone": "9000000003",
            "address_line1": f"Origin Road {tag}",
            "city": "Pune",
            "state": "MH",
            "pincode": "411001",
        },
        "new_delivery_address": {
            "name": "NDR Consignee",
            "phone": "8888888888",
            "address_line1": "Consignee Road 1",
            "city": "Mumbai",
            "state": "MH",
            "pincode": B2C_DELIVERY_PINCODE,
        },
        "packages": [
            {"length": 10.0, "breadth": 10.0, "height": 10.0, "weight": 1.0, "box_count": 2}
        ],
        "payment_details": {
            "freight_payment_mode": "PREPAID",
            "is_cod": False,
            "cod_amount": 0.0,
            "shipment_total_value": total_value,
        },
    }
    if reverse:
        payload["reason_for_return"] = "Customer return"
    return payload


async def _create(client: AsyncClient, **kwargs) -> dict:
    res = await client.post(SHIPMENTS_URL, json=_shipment_payload(**kwargs), headers=HEADERS)
    assert res.status_code == 201, res.text
    return res.json()


async def _set_status(db_session, shipment_id: str, new_status: PickupStatus) -> None:
    """Fast-forward the lifecycle directly in the test transaction."""
    shipment = await db_session.get(PickupRequest, uuid.UUID(shipment_id))
    shipment.status = new_status
    db_session.add(shipment)
    await db_session.flush()


async def _raise(
    client: AsyncClient,
    shipment_id: str,
    reason: NdrExceptionReason,
    *,
    expected: int = 200,
    **extra,
) -> dict:
    body = {"status": "EXCEPTION", "ndr_reason": reason.value, "comment": "Ops raised", **extra}
    res = await client.patch(f"{SHIPMENTS_URL}/{shipment_id}", json=body, headers=HEADERS)
    assert res.status_code == expected, res.text
    return res.json()


async def _act(
    client: AsyncClient, shipment_id: str, action: NdrAction, *, expected: int = 200, **fields
) -> dict:
    res = await client.post(
        f"{EXCEPTIONS_URL}/{shipment_id}/actions",
        json={"action": action.value, **fields},
        headers=HEADERS,
    )
    assert res.status_code == expected, res.text
    return res.json()


async def _find_row(client: AsyncClient, flow: str, tracking_id: str) -> Optional[dict]:
    res = await client.get(
        EXCEPTIONS_URL, params={"service_flow": flow, "search": tracking_id}, headers=HEADERS
    )
    assert res.status_code == 200, res.text
    return next((r for r in res.json()["items"] if r["tracking_id"] == tracking_id), None)


async def _summary(client: AsyncClient, flow: str) -> dict:
    res = await client.get(f"{EXCEPTIONS_URL}/summary", params={"service_flow": flow}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    body["by_category"] = {c["category"]: c for c in body["categories"]}
    return body


async def _admin() -> User:
    return await app.dependency_overrides[get_current_active_user]()


async def _tenant() -> Tenant:
    return await app.dependency_overrides[get_tenant_from_header]()


async def _make_customer(db_session) -> User:
    """A real customer row (FKs on activities / wallets need it), rolled back after the test."""
    tenant = await _tenant()
    tag = uuid.uuid4().hex[:10]
    customer = User(
        supabase_user_id=f"ndr-test-{tag}",
        email=f"ndr-{tag}@example.com",
        role=UserRole.customer,
        service_scope=ServiceScope.BOTH,
        tenant_id=tenant.id,
    )
    db_session.add(customer)
    await db_session.flush()
    return customer


def _as_user(user: User) -> None:
    async def _override():
        return user

    app.dependency_overrides[get_current_active_user] = _override


def _with_tenant(tenant: Tenant) -> None:
    async def _override():
        return tenant

    app.dependency_overrides[get_tenant_from_header] = _override


async def _wallet_balance(db_session, user_id: uuid.UUID, tenant_id: uuid.UUID) -> float:
    wallet = (
        await db_session.exec(
            select(UserWallet)
            .where(UserWallet.user_id == user_id, UserWallet.tenant_id == tenant_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    return round(float(wallet.balance), 2) if wallet else 0.0


# --------------------------------------------------------------------------- pure rules


@pytest.mark.asyncio
async def test_allowed_actions_matrix_rules():
    fwd, rev = ShipmentType.FORWARD, ShipmentType.REVERSE
    assert ndr_rules.allowed_actions(NdrExceptionReason.DAMAGED, fwd, False) == [
        NdrAction.REATTEMPT,
        NdrAction.RETURN_TO_ORIGIN,
    ]
    assert ndr_rules.allowed_actions(NdrExceptionReason.DAMAGED, fwd, True) == [
        NdrAction.RETURN_TO_ORIGIN,
        NdrAction.REPACK_AND_DELIVER,
    ]
    # CUSTOMER_UNAVAILABLE is an alias of CONSIGNEE_UNAVAILABLE.
    for is_b2b in (False, True):
        assert ndr_rules.allowed_actions(
            NdrExceptionReason.CUSTOMER_UNAVAILABLE, fwd, is_b2b
        ) == ndr_rules.allowed_actions(NdrExceptionReason.CONSIGNEE_UNAVAILABLE, fwd, is_b2b)
    # Pickup-stage (NPR) exceptions only allow reschedule / cancel.
    for reason in (NdrExceptionReason.PICKUP_FAILED, NdrExceptionReason.CONSIGNEE_REFUSED):
        assert ndr_rules.allowed_actions(reason, rev, False) == [
            NdrAction.RESCHEDULE_PICKUP,
            NdrAction.CANCEL_PICKUP,
        ]
    # Reverse shipments are never offered RTO.
    for reason in NdrExceptionReason:
        for is_b2b in (False, True):
            assert NdrAction.RETURN_TO_ORIGIN not in ndr_rules.allowed_actions(reason, rev, is_b2b)
    assert ndr_rules.allowed_actions(None, fwd, False) == []
    assert ndr_rules.allowed_actions(NdrExceptionReason.FREIGHT_COLLECTION, fwd, True) == [
        NdrAction.ACKNOWLEDGE_CHARGES
    ]
    # Attempt limits.
    assert ndr_rules.attempt_limit_outcome(NdrExceptionReason.CONSIGNEE_REFUSED, fwd, 2) is None
    assert (
        ndr_rules.attempt_limit_outcome(NdrExceptionReason.CONSIGNEE_REFUSED, fwd, 3)
        == PickupStatus.RTO_INITIATED
    )
    assert (
        ndr_rules.attempt_limit_outcome(NdrExceptionReason.PICKUP_FAILED, rev, 3)
        == PickupStatus.CANCELLED
    )
    assert ndr_rules.attempt_limit_outcome(NdrExceptionReason.DAMAGED, fwd, 5) is None
    # Categories.
    assert ndr_rules.categorize(NdrExceptionReason.CONSIGNEE_REFUSED, fwd, False, True) == ExceptionCategory.NDR
    assert ndr_rules.categorize(NdrExceptionReason.PICKUP_FAILED, rev, False, True) == ExceptionCategory.PICKUP_FAILED
    assert ndr_rules.categorize(NdrExceptionReason.DAMAGED, fwd, False, False) == ExceptionCategory.NON_ACTIONABLE
    assert ndr_rules.categorize(NdrExceptionReason.WEIGHT_DISCREPANCY, fwd, True, True) == ExceptionCategory.MEASURED_WEIGHT
    assert len(ndr_rules.FLOW_CATEGORIES[ServiceFlow.B2B]) == 11


# --------------------------------------------------------------------------- API flows


@pytest.mark.asyncio
async def test_raise_list_and_matrix_allow_deny(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client)
        await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)

        raised = await _raise(
            client, ship["id"], NdrExceptionReason.DAMAGED, ndr_remark="Outer box crushed"
        )
        assert raised["status"] == "EXCEPTION"
        assert raised["ndr_remark"] == "Outer box crushed"
        assert raised["exception_raised_at"] is not None
        assert raised["ndr_attempt_count"] == 0

        row = await _find_row(client, "B2C", ship["tracking_id"])
        assert row is not None
        assert row["category"] == "SHIPMENT_EXCEPTIONS"
        assert row["allowed_actions"] == ["REATTEMPT", "RETURN_TO_ORIGIN"]
        assert row["is_actionable"] is True
        assert row["aging_days"] == 0
        assert row["last_remark"] == "Outer box crushed"
        assert row["max_attempts"] == ndr_rules.MAX_NDR_ATTEMPTS
        assert row["box_count"] == 2
        assert row["payment_mode"] == "PREPAID"
        assert row["consignee"]["pincode"] == B2C_DELIVERY_PINCODE
        # Search by order reference also works; B2B list doesn't contain this B2C row.
        res = await client.get(
            EXCEPTIONS_URL,
            params={"service_flow": "B2C", "search": ship["order_reference_id"]},
            headers=HEADERS,
        )
        assert any(r["shipment_id"] == ship["id"] for r in res.json()["items"])
        assert await _find_row(client, "B2B", ship["tracking_id"]) is None

        denied = await _act(client, ship["id"], NdrAction.UPDATE_EWAY_BILL, expected=400)
        assert "not allowed" in denied["detail"]

        resolved = await _act(client, ship["id"], NdrAction.REATTEMPT, notes="Deliver anyway")
        assert resolved["status"] == "IN_TRANSIT"
        assert resolved["ndr_reason"] is None
        assert resolved["allowed_actions"] == []

        res = await client.get(f"{SHIPMENTS_URL}/{ship['id']}/timeline", headers=HEADERS)
        assert any(a["diff"].get("ndr_action") == "REATTEMPT" for a in res.json())

        # No active exception any more.
        await _act(client, ship["id"], NdrAction.REATTEMPT, expected=400)


@pytest.mark.asyncio
async def test_three_failed_attempts_auto_rto(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client)
        await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)

        first = await _raise(client, ship["id"], NdrExceptionReason.CONSIGNEE_UNAVAILABLE)
        assert first["ndr_attempt_count"] == 1
        row = await _find_row(client, "B2C", ship["tracking_id"])
        assert row["category"] == "NDR"
        assert row["attempts"] == 1
        await _act(client, ship["id"], NdrAction.REATTEMPT, preferred_date=str(date.today()))

        second = await _raise(client, ship["id"], NdrExceptionReason.CUSTOMER_UNAVAILABLE)
        assert second["ndr_attempt_count"] == 2
        await _act(client, ship["id"], NdrAction.REATTEMPT)

        third = await _raise(client, ship["id"], NdrExceptionReason.CONSIGNEE_REFUSED)
        assert third["ndr_attempt_count"] == 3
        assert third["status"] == "RTO_INITIATED"
        assert third["ndr_reason"] is None

        res = await client.get(f"{SHIPMENTS_URL}/{ship['id']}/timeline", headers=HEADERS)
        assert any(a["diff"].get("ndr_auto_resolution") == "RTO_INITIATED" for a in res.json())


@pytest.mark.asyncio
async def test_reverse_pickup_failed_reschedule_limit(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client, reverse=True)
        tomorrow = date.today() + timedelta(days=1)

        await _set_status(db_session, ship["id"], PickupStatus.ASSIGNED)
        await _raise(client, ship["id"], NdrExceptionReason.PICKUP_FAILED, ndr_remark="Door locked")
        row = await _find_row(client, "B2C", ship["tracking_id"])
        assert row["category"] == "PICKUP_FAILED"
        assert row["allowed_actions"] == ["RESCHEDULE_PICKUP", "CANCEL_PICKUP"]
        await _act(client, ship["id"], NdrAction.REATTEMPT, expected=400)
        await _act(
            client,
            ship["id"],
            NdrAction.RESCHEDULE_PICKUP,
            expected=400,
            preferred_date=str(date.today() - timedelta(days=1)),
        )
        rescheduled = await _act(
            client, ship["id"], NdrAction.RESCHEDULE_PICKUP, preferred_date=str(tomorrow)
        )
        assert rescheduled["status"] == "OPEN"  # not linked to a Pickup Request
        shipment = await db_session.get(PickupRequest, uuid.UUID(ship["id"]))
        assert shipment.requested_pickup_date == tomorrow

        await _set_status(db_session, ship["id"], PickupStatus.ASSIGNED)
        await _raise(client, ship["id"], NdrExceptionReason.CONSIGNEE_UNAVAILABLE)
        await _act(client, ship["id"], NdrAction.RESCHEDULE_PICKUP)

        await _set_status(db_session, ship["id"], PickupStatus.ASSIGNED)
        third = await _raise(client, ship["id"], NdrExceptionReason.PICKUP_FAILED)
        assert third["ndr_attempt_count"] == 3
        assert third["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_update_consignee_same_pincode_rule(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client)
        await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        await _raise(client, ship["id"], NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED)

        await _act(client, ship["id"], NdrAction.UPDATE_CONSIGNEE, expected=400)
        other_pin = await _act(
            client,
            ship["id"],
            NdrAction.UPDATE_CONSIGNEE,
            expected=400,
            consignee_address_line1="Flat 9, New Tower",
            consignee_pincode="110001",
        )
        assert "same pincode" in other_pin["detail"]

        updated = await _act(
            client,
            ship["id"],
            NdrAction.UPDATE_CONSIGNEE,
            consignee_phone="9123456780",
            consignee_address_line1="Flat 9, New Tower",
            landmark="Near Metro",
            consignee_pincode=B2C_DELIVERY_PINCODE,
        )
        assert updated["status"] == "IN_TRANSIT"
        res = await client.get(f"{SHIPMENTS_URL}/{ship['id']}", headers=HEADERS)
        delivery = res.json()["delivery_address"]
        assert delivery["id"] != ship["delivery_address"]["id"]  # new snapshot
        assert delivery["phone"] == "9123456780"
        assert delivery["address_line1"] == "Flat 9, New Tower"
        assert delivery["pincode"] == B2C_DELIVERY_PINCODE


@pytest.mark.asyncio
async def test_charge_acknowledgement_debits_wallet(db_session):
    admin = await _admin()
    tenant = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client, b2b=True)
        await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)

        await _raise(client, ship["id"], NdrExceptionReason.FREIGHT_COLLECTION, expected=400)
        raised = await _raise(
            client, ship["id"], NdrExceptionReason.FREIGHT_COLLECTION, charge_amount=123.45
        )
        assert raised["charge_amount"] == 123.45
        row = await _find_row(client, "B2B", ship["tracking_id"])
        assert row["category"] == "FREIGHT_COLLECTION"
        assert row["charge_amount"] == 123.45

        before = await _wallet_balance(db_session, admin.id, tenant.id)
        done = await _act(client, ship["id"], NdrAction.ACKNOWLEDGE_CHARGES)
        assert done["status"] == "IN_TRANSIT"
        assert done["charge_amount"] is None
        after = await _wallet_balance(db_session, admin.id, tenant.id)
        assert round(before - after, 2) == 123.45

        txn = (
            await db_session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.shipment_id == uuid.UUID(ship["id"]),
                    WalletTransaction.txn_type == WalletTxnType.FREIGHT_COLLECTION.value,
                )
            )
        ).first()
        assert txn is not None
        assert round(float(txn.amount), 2) == 123.45
        assert txn.receipt_number.startswith("FRC-")


@pytest.mark.asyncio
async def test_weight_accept_and_dispute(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        accepted = await _create(client, b2b=True)
        disputed = await _create(client, b2b=True)
        for ship in (accepted, disputed):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)

        await _raise(client, accepted["id"], NdrExceptionReason.WEIGHT_DISCREPANCY, expected=400)
        await _raise(
            client, accepted["id"], NdrExceptionReason.WEIGHT_DISCREPANCY, measured_weight_kg=25.0
        )
        done = await _act(client, accepted["id"], NdrAction.ACCEPT_WEIGHT)
        assert done["status"] == "IN_TRANSIT"
        res = await client.get(f"{SHIPMENTS_URL}/{accepted['id']}", headers=HEADERS)
        assert res.json()["payment_details"]["chargeable_weight"] == 25.0
        txn = (
            await db_session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.shipment_id == uuid.UUID(accepted["id"]),
                    WalletTransaction.txn_type == WalletTxnType.WEIGHT_AUDIT_DEBIT.value,
                )
            )
        ).first()
        assert txn is not None and float(txn.amount) > 0

        await _raise(
            client, disputed["id"], NdrExceptionReason.WEIGHT_DISCREPANCY, charge_amount=80.0
        )
        held = await _act(client, disputed["id"], NdrAction.DISPUTE_WEIGHT, notes="Weighed 2kg at dock")
        assert held["status"] == "EXCEPTION"
        assert held["awaiting_ops"] is True
        assert held["is_actionable"] is False
        assert held["allowed_actions"] == []
        await _act(client, disputed["id"], NdrAction.ACCEPT_WEIGHT, expected=400)


@pytest.mark.asyncio
async def test_customer_scoping_cannot_raise_and_finlock(db_session):
    admin = await _admin()
    tenant = await _tenant()
    customer = await _make_customer(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _as_user(customer)
        try:
            mine = await _create(client)
        finally:
            _as_user(admin)
        theirs = await _create(client)
        for ship in (mine, theirs):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        await _raise(client, mine["id"], NdrExceptionReason.ADDITIONAL_CHARGES, charge_amount=250.0)
        await _raise(client, theirs["id"], NdrExceptionReason.DAMAGED)

        strict_tenant = Tenant(
            **{
                **tenant.model_dump(),
                "settings": {
                    **(tenant.settings or {}),
                    "wallet_config": {
                        **((tenant.settings or {}).get("wallet_config") or {}),
                        "strict_finlock": True,
                    },
                },
            }
        )
        _as_user(customer)
        try:
            # Customers can NOT raise exceptions.
            await _raise(client, mine["id"], NdrExceptionReason.DAMAGED, expected=403)

            res = await client.get(EXCEPTIONS_URL, params={"service_flow": "B2C"}, headers=HEADERS)
            ids = {r["shipment_id"] for r in res.json()["items"]}
            assert mine["id"] in ids and theirs["id"] not in ids
            summary = await _summary(client, "B2C")
            assert summary["total"] == 1
            assert summary["actionable"] == 1
            assert summary["by_category"]["SHIPMENT_EXCEPTIONS"]["total"] == 1

            await _act(client, theirs["id"], NdrAction.REATTEMPT, expected=404)

            # Finlock: the customer's wallet can't cover the charge.
            _with_tenant(strict_tenant)
            blocked = await _act(client, mine["id"], NdrAction.ACKNOWLEDGE_CHARGES, expected=400)
            assert "Finlock" in blocked["detail"]
            row = await _find_row(client, "B2C", mine["tracking_id"])
            assert row["status"] == "EXCEPTION"

            # Without Finlock the debit goes through (balance may go negative).
            _with_tenant(tenant)
            before = await _wallet_balance(db_session, customer.id, tenant.id)
            cleared = await _act(client, mine["id"], NdrAction.ACKNOWLEDGE_CHARGES)
            assert cleared["status"] == "IN_TRANSIT"
            after = await _wallet_balance(db_session, customer.id, tenant.id)
            assert round(before - after, 2) == 250.0
        finally:
            _as_user(admin)
            _with_tenant(tenant)


@pytest.mark.asyncio
async def test_bulk_action_limits_and_partial_failures(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        too_many = [str(uuid.uuid4()) for _ in range(ndr_rules.MAX_BULK_ACTION_SHIPMENTS + 1)]
        res = await client.post(
            f"{EXCEPTIONS_URL}/bulk-action",
            json={"action": "REATTEMPT", "shipment_ids": too_many},
            headers=HEADERS,
        )
        assert res.status_code == 422
        res = await client.post(
            f"{EXCEPTIONS_URL}/bulk-action",
            json={"action": "UPDATE_EWAY_BILL", "shipment_ids": [str(uuid.uuid4())]},
            headers=HEADERS,
        )
        assert res.status_code == 400

        ndr = await _create(client)
        not_on_hold = await _create(client)
        for ship in (ndr, not_on_hold):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        await _raise(client, ndr["id"], NdrExceptionReason.CONSIGNEE_REFUSED)
        missing = str(uuid.uuid4())

        res = await client.post(
            f"{EXCEPTIONS_URL}/bulk-action",
            json={"action": "RETURN_TO_ORIGIN", "shipment_ids": [ndr["id"], not_on_hold["id"], missing]},
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["succeeded"] == [ndr["id"]]
        failed = {f["shipment_id"]: f["reason"] for f in body["failed"]}
        assert set(failed) == {not_on_hold["id"], missing}
        assert "no active exception" in failed[not_on_hold["id"]]
        assert failed[missing] == "Shipment not found"

        res = await client.get(f"{SHIPMENTS_URL}/{ndr['id']}", headers=HEADERS)
        assert res.json()["status"] == "RTO_INITIATED"


@pytest.mark.asyncio
async def test_summary_counts_and_hold_is_non_actionable(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        b2c_before = await _summary(client, "B2C")
        b2b_before = await _summary(client, "B2B")
        assert set(b2c_before["by_category"]) == {c.value for c in ndr_rules.FLOW_CATEGORIES[ServiceFlow.B2C]}
        assert set(b2b_before["by_category"]) == {c.value for c in ndr_rules.FLOW_CATEGORIES[ServiceFlow.B2B]}

        b2c = await _create(client)
        b2b = await _create(client, b2b=True)
        for ship in (b2c, b2b):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        await _raise(client, b2c["id"], NdrExceptionReason.CONSIGNEE_REFUSED)
        await _raise(client, b2b["id"], NdrExceptionReason.SHORT_SHIPMENT)

        b2c_after = await _summary(client, "B2C")
        assert b2c_after["total"] == b2c_before["total"] + 1
        assert b2c_after["by_category"]["NDR"]["total"] == b2c_before["by_category"]["NDR"]["total"] + 1

        b2b_after = await _summary(client, "B2B")
        short_before = b2b_before["by_category"]["SHORT_SHIPMENTS"]
        short_after = b2b_after["by_category"]["SHORT_SHIPMENTS"]
        assert short_after["total"] == short_before["total"] + 1
        assert short_after["actionable"] == short_before["actionable"] + 1

        held = await _act(client, b2b["id"], NdrAction.HOLD)
        assert held["status"] == "EXCEPTION" and held["awaiting_ops"] is True
        b2b_held = await _summary(client, "B2B")
        assert b2b_held["by_category"]["SHORT_SHIPMENTS"]["total"] == short_before["total"] + 1
        assert b2b_held["by_category"]["SHORT_SHIPMENTS"]["actionable"] == short_before["actionable"]
        assert b2b_held["non_actionable"] == b2b_before["non_actionable"] + 1

        res = await client.get(
            EXCEPTIONS_URL,
            params={"service_flow": "B2B", "category": "SHORT_SHIPMENTS", "actionable_only": "true"},
            headers=HEADERS,
        )
        assert all(r["shipment_id"] != b2b["id"] for r in res.json()["items"])

        res = await client.get(
            EXCEPTIONS_URL, params={"service_flow": "B2C", "category": "DAMAGES"}, headers=HEADERS
        )
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_legacy_resolve_exception_mapping(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        appointment = await _create(client, b2b=True)
        damaged = await _create(client)
        for ship in (appointment, damaged):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        await _raise(client, appointment["id"], NdrExceptionReason.APPOINTMENT_NEEDED)
        await _raise(client, damaged["id"], NdrExceptionReason.DAMAGED)

        def _legacy_url(ship: dict) -> str:
            return f"{SHIPMENTS_URL}/{ship['id']}/resolve-exception"

        res = await client.post(_legacy_url(damaged), json={"action": "FOO"}, headers=HEADERS)
        assert res.status_code == 400
        res = await client.post(_legacy_url(damaged), json={"action": "HOLD_SHIPMENT"}, headers=HEADERS)
        assert res.status_code == 400  # HOLD is not allowed for B2C DAMAGED

        res = await client.post(
            _legacy_url(appointment),
            json={"action": "DELIVER_WITHOUT_APPOINTMENT", "notes": "Customer authorised"},
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "IN_TRANSIT"

        res = await client.post(_legacy_url(damaged), json={"action": "RETURN_TO_SENDER"}, headers=HEADERS)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "RTO_INITIATED"
