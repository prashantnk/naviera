"""
Wave W2b money-path guards (go-live board M1, M2, M6, M7, O2 + public tracking).

1. M1 / B16 (D85): a customer may book POSTPAID; it is billed to their own wallet
   (billing channel WALLET, SPEND + INVOICE). Staff POSTPAID stays on account (NONE).
2. M2 / D26 / B7: TO_PAY + COD stores goods-only COD and the freight separately; it
   settles goods-only to the merchant; summary matches.
3. M6 / D30 / D55: ops / support / read-only can't consent to a wallet charge (403);
   the shipment's customer and owner/admin can; a double acknowledge debits once, the
   GST-exclusive charge plus GST, with its own DEBIT_NOTE.
4. M7 / C2: merchant RTO and the automatic RTO both bill the RTO leg once as
   RTO_FREIGHT + DEBIT_NOTE (even under Finlock).
5. O2: a B2B LR flagged only by `pickup_strategy` gets the B2B label and B2B re-pricing.
6. Public tracking never shows internal wallet / money text.

All writes happen inside the per-test transaction from conftest (rolled back).
"""

import uuid
from datetime import date
from typing import List, Optional

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.money import to_money
from app.main import app
from app.models.delhivery_modules import BillingInvoice, CodRemittance, InvoiceNoteType
from app.models.pickups import NdrAction, NdrExceptionReason, PaymentDetails, PickupRequest, PickupStatus
from app.models.repricing import BillingChannel
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.models.wallet import UserWallet, WalletTransaction, WalletTxnType
from app.repositories.shipments import ShipmentRepository
from app.services.cod_payout import door_collectible
from app.services.delhivery_modules import SEPARATE_CHARGE_LINE_FLAG, tenant_gst_rate
from app.services.label import LabelGenerator
from app.services.shipment import RTO_FREIGHT_REMARK_TEMPLATE
from app.services.wallet import indian_financial_year_label, today_ist
from golden_journeys.golden_env import allow_to_pay_bookings

HEADERS = {"X-Tenant-Slug": "naviera"}
API = settings.API_V1_STR
SHIPMENTS_URL = f"{API}/shipments"
EXCEPTIONS_URL = f"{API}/exceptions"
GOODS_VALUE = 1000.0
ADDITIONAL_CHARGE_EXCL_GST = 100.0
"""Mathadi / union charge as ops enter it: GST-exclusive (D55)."""
GST_RATE = 0.18
"""The test tenant's GST rate, added on top of an additional charge (D55)."""
ADDITIONAL_CHARGE_GROSS = 118.0
"""What one acknowledged additional charge debits: 100.00 + 18 % GST."""
ADDITIONAL_CHARGE_RECEIPT_PREFIX = "ADC"
"""Wallet receipt family of an additional charge (`ADC-<FY>-<8 hex>`, B12)."""


# --------------------------------------------------------------------------- helpers


def _payload(
    *,
    freight_mode: str = "PREPAID",
    cod: bool = False,
    add_shipping_to_cod: bool = False,
    pickup_strategy: Optional[str] = None,
) -> dict:
    """Minimal valid B2C booking (B2B only when `pickup_strategy` is given)."""
    tag = uuid.uuid4().hex[:8]
    body = {
        "order_reference_id": f"W2B-{tag}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "product_category": "ELECTRONICS",
        "new_pickup_address": {
            "name": f"W2B WH {tag}", "phone": "9000000007", "address_line1": f"Unit {tag}",
            "city": "Gurugram", "state": "HR", "pincode": "122001",
        },
        "new_delivery_address": {
            "name": "W2B Consignee", "phone": "8888888888", "address_line1": "Road 7",
            "city": "Mumbai", "state": "MH", "pincode": "400001",
        },
        "packages": [{"length": 10.0, "breadth": 10.0, "height": 10.0, "weight": 1.0, "box_count": 1}],
        "payment_details": {
            "freight_payment_mode": freight_mode,
            "is_cod": cod,
            "cod_amount": GOODS_VALUE if cod else 0.0,
            "add_shipping_to_cod": add_shipping_to_cod,
            "shipment_total_value": GOODS_VALUE,
        },
    }
    if pickup_strategy is not None:
        body["pickup_strategy"] = pickup_strategy
    return body


async def _tenant() -> Tenant:
    return await app.dependency_overrides[get_tenant_from_header]()


async def _real_user(db_session, role: UserRole) -> User:
    """A real user row (FKs on wallets / activities need it), rolled back after the test."""
    tenant = await _tenant()
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"w2b-{role.value}-{tag}",
        email=f"w2b-{role.value}-{tag}@example.com",
        role=role,
        service_scope=ServiceScope.BOTH,
        tenant_id=tenant.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _as_user(user: User) -> None:
    async def _override():
        return user

    app.dependency_overrides[get_current_active_user] = _override


def _with_tenant(tenant: Tenant) -> None:
    async def _override():
        return tenant

    app.dependency_overrides[get_tenant_from_header] = _override


@pytest.fixture
async def restore_overrides():
    original_user = app.dependency_overrides[get_current_active_user]
    original_tenant = app.dependency_overrides[get_tenant_from_header]
    yield await original_user()
    app.dependency_overrides[get_current_active_user] = original_user
    app.dependency_overrides[get_tenant_from_header] = original_tenant


async def _create(client: AsyncClient, actor: User, **kwargs) -> dict:
    _as_user(actor)
    if kwargs.get("freight_mode") == "TO_PAY":
        with allow_to_pay_bookings():
            res = await client.post(SHIPMENTS_URL, json=_payload(**kwargs), headers=HEADERS)
    else:
        res = await client.post(SHIPMENTS_URL, json=_payload(**kwargs), headers=HEADERS)
    assert res.status_code == 201, res.text
    return res.json()


async def _set_status(db_session, shipment_id: str, new_status: PickupStatus) -> None:
    shipment = await db_session.get(PickupRequest, uuid.UUID(shipment_id))
    shipment.status = new_status
    db_session.add(shipment)
    await db_session.flush()


async def _raise(client: AsyncClient, admin: User, shipment_id: str, reason: NdrExceptionReason, **extra) -> dict:
    _as_user(admin)
    body = {"status": "EXCEPTION", "ndr_reason": reason.value, "comment": "Ops raised", **extra}
    res = await client.patch(f"{SHIPMENTS_URL}/{shipment_id}", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


async def _act(client: AsyncClient, actor: User, shipment_id: str, action: NdrAction, *, expected: int = 200) -> dict:
    _as_user(actor)
    res = await client.post(
        f"{EXCEPTIONS_URL}/{shipment_id}/actions", json={"action": action.value}, headers=HEADERS
    )
    assert res.status_code == expected, res.text
    return res.json()


async def _balance(db_session, user_id: uuid.UUID, tenant_id: uuid.UUID) -> float:
    wallet = (
        await db_session.exec(
            select(UserWallet)
            .where(UserWallet.user_id == user_id, UserWallet.tenant_id == tenant_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    return round(float(wallet.balance), 2) if wallet else 0.0


async def _txns(db_session, shipment_id: str, txn_type: WalletTxnType) -> List[WalletTransaction]:
    rows = await db_session.exec(
        select(WalletTransaction).where(
            WalletTransaction.shipment_id == uuid.UUID(shipment_id),
            WalletTransaction.txn_type == txn_type.value,
        )
    )
    return list(rows.all())


async def _payment(db_session, shipment_id: str) -> PaymentDetails:
    """The shipment's stored payment row, re-read from the database."""
    return (
        await db_session.exec(
            select(PaymentDetails)
            .where(PaymentDetails.pickup_id == uuid.UUID(shipment_id))
            .execution_options(populate_existing=True)
        )
    ).one()


async def _notes(db_session, shipment_id: str, note_type: InvoiceNoteType) -> List[BillingInvoice]:
    """GST documents of one type issued for a shipment."""
    rows = await db_session.exec(
        select(BillingInvoice).where(
            BillingInvoice.shipment_id == uuid.UUID(shipment_id),
            BillingInvoice.note_type == note_type.value,
        )
    )
    return list(rows.all())


def _strict_finlock(tenant: Tenant) -> Tenant:
    tenant_settings = dict(tenant.settings or {})
    wallet_cfg = dict(tenant_settings.get("wallet_config") or {})
    wallet_cfg["strict_finlock"] = True
    tenant_settings["wallet_config"] = wallet_cfg
    dump = tenant.model_dump()
    dump["settings"] = tenant_settings
    return Tenant(**dump)


# --------------------------------------------------------------------------- M1


@pytest.mark.asyncio
async def test_customer_postpaid_billed_to_wallet_staff_postpaid_on_account(db_session, restore_overrides):
    admin = restore_overrides
    tenant = await _tenant()
    customer = await _real_user(db_session, UserRole.customer)
    ops = await _real_user(db_session, UserRole.operations_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # B16 / D85: a customer's own POSTPAID booking is billed to their wallet.
        start = await _balance(db_session, customer.id, tenant.id)
        postpaid = await _create(client, customer, freight_mode="POSTPAID")
        payment = postpaid["payment_details"]
        assert payment["freight_payment_mode"] == "POSTPAID"
        assert payment["pricing_breakdown"]["billing_channel"] == BillingChannel.WALLET.value
        bill = round(payment["total_logistics_cost"], 2)
        spend = await _txns(db_session, postpaid["id"], WalletTxnType.SPEND)
        assert len(spend) == 1
        assert round(float(spend[0].amount), 2) == bill
        assert round(start - await _balance(db_session, customer.id, tenant.id), 2) == bill
        invoices = await _notes(db_session, postpaid["id"], InvoiceNoteType.INVOICE)
        assert len(invoices) == 1
        assert round(invoices[0].total_amount, 2) == bill

        to_pay = await _create(client, customer, freight_mode="TO_PAY")
        assert to_pay["payment_details"]["freight_payment_mode"] == "TO_PAY"
        assert to_pay["payment_details"]["pricing_breakdown"]["billing_channel"] == BillingChannel.NONE.value

        # #558 (3a): walk-in on-behalf is not in MVP; staff POSTPAID is also wallet-billed.
        for staff in (admin, ops):
            booked = await _create(client, staff, freight_mode="POSTPAID")
            assert booked["payment_details"]["freight_payment_mode"] == "POSTPAID"
            assert booked["payment_details"]["pricing_breakdown"]["billing_channel"] == BillingChannel.WALLET.value
            assert len(await _txns(db_session, booked["id"], WalletTxnType.SPEND)) == 1
            assert len(await _notes(db_session, booked["id"], InvoiceNoteType.INVOICE)) == 1


# --------------------------------------------------------------------------- M2


@pytest.mark.asyncio
async def test_to_pay_cod_settles_goods_only(db_session, restore_overrides):
    admin = restore_overrides
    tenant = await _tenant()
    customer = await _real_user(db_session, UserRole.customer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        to_pay = await _create(client, customer, freight_mode="TO_PAY", cod=True, add_shipping_to_cod=True)
        prepaid = await _create(client, customer, cod=True, add_shipping_to_cod=True)
        to_pay_freight = to_pay["payment_details"]["total_logistics_cost"]
        # B7 / M-B3: TO_PAY stores the goods-only COD and the freight to collect apart;
        # the rider still collects goods + freight at the door.
        assert to_pay["payment_details"]["cod_amount"] == GOODS_VALUE
        assert to_pay["payment_details"]["freight_collectible"] == to_pay_freight
        assert door_collectible(await _payment(db_session, to_pay["id"])) == to_money(GOODS_VALUE) + to_money(
            to_pay_freight
        )
        prepaid_cod = prepaid["payment_details"]["cod_amount"]
        for ship in (to_pay, prepaid):
            await _set_status(db_session, ship["id"], PickupStatus.COMPLETED)

        expected_payout = round(GOODS_VALUE + prepaid_cod, 2)
        _as_user(customer)
        overview = await client.get(f"{API}/wallet", headers=HEADERS)
        assert overview.status_code == 200, overview.text
        assert overview.json()["summary"]["collectible_cod"] == expected_payout

        # A customer is paid in the finance team's remittance cycle, never self-settles.
        res = await client.post(f"{API}/wallet/settle-cod", headers=HEADERS)
        assert res.status_code == 403, res.text

        # Owner / Admin settles the merchant's delivered COD into the merchant's wallet.
        _as_user(admin)
        res = await client.post(
            f"{API}/wallet/settle-cod",
            params={"merchant_user_id": str(customer.id)},
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        assert res.json()["settled_count"] == 2
        assert res.json()["settled_amount"] == expected_payout

        _as_user(customer)
        overview = await client.get(f"{API}/wallet", headers=HEADERS)
        assert overview.json()["summary"]["collectible_cod"] == 0.0

    to_pay_txn = (await _txns(db_session, to_pay["id"], WalletTxnType.COD_SETTLEMENT))[0]
    assert round(float(to_pay_txn.amount), 2) == GOODS_VALUE
    prepaid_txn = (await _txns(db_session, prepaid["id"], WalletTxnType.COD_SETTLEMENT))[0]
    assert round(float(prepaid_txn.amount), 2) == prepaid_cod

    remittance = (
        await db_session.exec(
            select(CodRemittance).where(
                CodRemittance.tenant_id == tenant.id, CodRemittance.merchant_user_id == customer.id
            )
        )
    ).first()
    breakdown = {row["shipment_id"]: row["amount_collected"] for row in remittance.shipment_breakdown}
    assert breakdown[to_pay["id"]] == GOODS_VALUE
    assert remittance.total_remittance == expected_payout


# --------------------------------------------------------------------------- M6


@pytest.mark.asyncio
async def test_charge_consent_rules_and_idempotent_acknowledge(db_session, restore_overrides):
    admin = restore_overrides
    tenant = await _tenant()
    customer = await _real_user(db_session, UserRole.customer)
    owner = await _real_user(db_session, UserRole.owner)
    blocked_staff = [
        await _real_user(db_session, role)
        for role in (UserRole.operations_user, UserRole.support_user, UserRole.read_only_user)
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        on_behalf = await _create(client, customer)
        self_ack = await _create(client, customer)
        weight = await _create(client, customer)
        for ship in (on_behalf, self_ack, weight):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        for ship in (on_behalf, self_ack):
            await _raise(
                client, admin, ship["id"], NdrExceptionReason.ADDITIONAL_CHARGES,
                charge_amount=ADDITIONAL_CHARGE_EXCL_GST,
            )
        await _raise(client, admin, weight["id"], NdrExceptionReason.WEIGHT_DISCREPANCY, charge_amount=40.0)

        start = await _balance(db_session, customer.id, tenant.id)
        for staff in blocked_staff:
            await _act(client, staff, on_behalf["id"], NdrAction.ACKNOWLEDGE_CHARGES, expected=403)
            await _act(client, staff, weight["id"], NdrAction.ACCEPT_WEIGHT, expected=403)
        _as_user(blocked_staff[-1])
        legacy = await client.post(
            f"{SHIPMENTS_URL}/{on_behalf['id']}/resolve-exception",
            json={"action": "ACKNOWLEDGE_CHARGES"},
            headers=HEADERS,
        )
        assert legacy.status_code == 403, legacy.text
        _as_user(blocked_staff[0])
        legacy = await client.post(
            f"{SHIPMENTS_URL}/{on_behalf['id']}/resolve-exception",
            json={"action": "ACKNOWLEDGE_CHARGES"},
            headers=HEADERS,
        )
        assert legacy.status_code == 403, legacy.text
        assert await _balance(db_session, customer.id, tenant.id) == start

        done = await _act(client, owner, on_behalf["id"], NdrAction.ACKNOWLEDGE_CHARGES)
        assert done["status"] == "IN_TRANSIT"
        await _act(client, owner, on_behalf["id"], NdrAction.ACKNOWLEDGE_CHARGES, expected=400)
        assert len(await _txns(db_session, on_behalf["id"], WalletTxnType.ADDITIONAL_CHARGE)) == 1

        await _act(client, customer, self_ack["id"], NdrAction.ACKNOWLEDGE_CHARGES)
        await _act(client, customer, self_ack["id"], NdrAction.ACKNOWLEDGE_CHARGES, expected=400)
        assert len(await _txns(db_session, self_ack["id"], WalletTxnType.ADDITIONAL_CHARGE)) == 1

        # D55: entered GST-exclusive, debited with GST on top, each with its own DEBIT_NOTE.
        assert tenant_gst_rate(tenant) == GST_RATE
        assert round(start - await _balance(db_session, customer.id, tenant.id), 2) == 2 * ADDITIONAL_CHARGE_GROSS
        receipt_prefix = f"{ADDITIONAL_CHARGE_RECEIPT_PREFIX}-{indian_financial_year_label(today_ist())}-"
        for ship in (on_behalf, self_ack):
            (charge,) = await _txns(db_session, ship["id"], WalletTxnType.ADDITIONAL_CHARGE)
            assert round(float(charge.amount), 2) == ADDITIONAL_CHARGE_GROSS
            assert charge.receipt_number.startswith(receipt_prefix), charge.receipt_number
            (note,) = await _notes(db_session, ship["id"], InvoiceNoteType.DEBIT_NOTE)
            assert round(note.total_amount, 2) == ADDITIONAL_CHARGE_GROSS
            assert note.line_items[0][SEPARATE_CHARGE_LINE_FLAG] is True

        _as_user(admin)
        timeline = await client.get(f"{SHIPMENTS_URL}/{on_behalf['id']}/timeline", headers=HEADERS)
        consent = next(a["diff"]["charge_accepted_by"] for a in timeline.json() if "charge_accepted_by" in a["diff"])
        assert consent["user_id"] == str(owner.id)
        assert consent["on_behalf_of_shipper"] is True


# --------------------------------------------------------------------------- M7


async def _assert_rto_billed(db_session, ship_json: dict, booked_total: float) -> None:
    """
    C2 / D50: the RTO leg is billed exactly once as an RTO_FREIGHT debit (never a SPEND)
    of the bill increase, with its own DEBIT_NOTE against the booking INVOICE.
    """
    payment = ship_json["payment_details"]
    rto_amount = round(payment["total_logistics_cost"] - booked_total, 2)
    assert payment["pricing_breakdown"]["rto_surcharge"] > 0
    assert rto_amount > 0
    (rto_txn,) = await _txns(db_session, ship_json["id"], WalletTxnType.RTO_FREIGHT)
    assert rto_txn.remarks == RTO_FREIGHT_REMARK_TEMPLATE.format(tracking_id=ship_json["tracking_id"])
    assert round(float(rto_txn.amount), 2) == rto_amount
    spend = await _txns(db_session, ship_json["id"], WalletTxnType.SPEND)
    assert [round(float(t.amount), 2) for t in spend] == [round(booked_total, 2)], "only the booking SPEND"
    (debit_note,) = await _notes(db_session, ship_json["id"], InvoiceNoteType.DEBIT_NOTE)
    assert round(debit_note.total_amount, 2) == rto_amount
    (invoice,) = await _notes(db_session, ship_json["id"], InvoiceNoteType.INVOICE)
    assert debit_note.original_invoice_id == invoice.id


@pytest.mark.asyncio
async def test_merchant_rto_and_auto_rto_bill_rto_freight(db_session, restore_overrides):
    admin = restore_overrides
    tenant = await _tenant()
    customer = await _real_user(db_session, UserRole.customer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        merchant_rto = await _create(client, customer)
        auto_rto = await _create(client, customer)
        for ship in (merchant_rto, auto_rto):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)

        # Merchant RTO, with Finlock on and a negative wallet: never blocked (D18).
        await _raise(client, admin, merchant_rto["id"], NdrExceptionReason.CONSIGNEE_REFUSED)
        assert await _balance(db_session, customer.id, tenant.id) < 0
        _with_tenant(_strict_finlock(tenant))
        done = await _act(client, customer, merchant_rto["id"], NdrAction.RETURN_TO_ORIGIN)
        _with_tenant(tenant)
        assert done["status"] == "RTO_INITIATED"
        _as_user(admin)
        res = await client.get(f"{SHIPMENTS_URL}/{merchant_rto['id']}", headers=HEADERS)
        await _assert_rto_billed(db_session, res.json(), merchant_rto["payment_details"]["total_logistics_cost"])

        # Automatic RTO after the 3rd failed attempt.
        for reason in (NdrExceptionReason.CONSIGNEE_UNAVAILABLE, NdrExceptionReason.CONSIGNEE_REFUSED):
            await _raise(client, admin, auto_rto["id"], reason)
            await _act(client, admin, auto_rto["id"], NdrAction.REATTEMPT)
        third = await _raise(client, admin, auto_rto["id"], NdrExceptionReason.CONSIGNEE_REFUSED)
        assert third["status"] == "RTO_INITIATED"
        await _assert_rto_billed(db_session, third, auto_rto["payment_details"]["total_logistics_cost"])


# --------------------------------------------------------------------------- O2


@pytest.mark.asyncio
async def test_pickup_strategy_lr_gets_b2b_label_and_b2b_repricing(db_session, restore_overrides):
    admin = restore_overrides
    tenant = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        lr = await _create(client, admin, pickup_strategy="DEFAULT")
        loaded = await ShipmentRepository(db_session).get_shipment_full_details(uuid.UUID(lr["id"]), tenant.id)
        plain_tenant = Tenant(**dict(tenant.model_dump(), settings={}))
        assert LabelGenerator._is_b2b(loaded, plain_tenant) is True
        res = await client.get(f"{SHIPMENTS_URL}/{lr['id']}/label", headers=HEADERS)
        assert res.status_code == 200 and res.content.startswith(b"%PDF")

        res = await client.post(
            f"{SHIPMENTS_URL}/{lr['id']}/audit-weight", json={"audited_weight_kg": 100.0}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        pb = res.json()["payment_details"]["pricing_breakdown"]
        assert pb["service_option"] == "PRIME_SURFACE"
        assert any(line["code"] == "DOCKET" and line["amount"] > 0 for line in pb["sell_lines"])
    audit_txn = (await _txns(db_session, lr["id"], WalletTxnType.WEIGHT_AUDIT_DEBIT))[0]
    assert audit_txn.service_category == "B2B"


# --------------------------------------------------------------------------- public tracking


@pytest.mark.asyncio
async def test_public_tracking_hides_wallet_text(db_session, restore_overrides):
    admin = restore_overrides
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # A measurement re-bill (B4) narrates only the weights; the money lives in the diff.
        # An acknowledged charge is an internal activity whose summary still carries INR.
        ship = await _create(client, admin)
        await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        await _raise(
            client, admin, ship["id"], NdrExceptionReason.ADDITIONAL_CHARGES, charge_amount=ADDITIONAL_CHARGE_EXCL_GST
        )
        await _act(client, admin, ship["id"], NdrAction.ACKNOWLEDGE_CHARGES)
        timeline = await client.get(f"{SHIPMENTS_URL}/{ship['id']}/timeline", headers=HEADERS)
        assert timeline.status_code == 200, timeline.text
        action = NdrAction.ACKNOWLEDGE_CHARGES.value
        internal_summary = f"Charges acknowledged: INR {ADDITIONAL_CHARGE_GROSS:.2f} debited ({action})"
        assert any(a["summary"] == internal_summary for a in timeline.json())

        # B-03: the public page shows only allow-listed milestones with fixed wording.
        public = await client.get(f"{API}/tracking/{ship['tracking_id']}", headers=HEADERS)
        assert public.status_code == 200, public.text
        body = public.json()
        events = body["timeline"]
        assert any(e["status_title"] == "Shipment on hold" for e in events)
        assert body["package_details"] == []
        for event in events:
            text = f"{event['status_title']} {event.get('message') or ''}"
            assert "Wallet Debited" not in text and "INR" not in text
            assert action not in text and NdrExceptionReason.ADDITIONAL_CHARGES.value not in text
