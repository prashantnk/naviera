"""
Go-live wave W2a: money correctness and cross-merchant isolation.

1. S5a: a customer with no rows sees empty remittance / invoice / dispute lists.
2. S5c + M4: weight claims (ownership 404, audit-required 400, final states,
   refund exactly once).
3. M2 + M3: COD remittance batches pay one merchant, exclude RTO / remitted /
   wallet-settled shipments, and pay goods-only on TO_PAY + COD (decision D26).
4. M5: GST split (taxable = total - engine GST; CGST+SGST vs IGST by place of
   supply) and sequential per-tenant / FY / type numbering under concurrency.

API writes run inside the per-test transaction from conftest (rolled back).
The concurrency test uses its own committed connections and deletes its rows.
"""

import asyncio
import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from golden_journeys.golden_env import allow_to_pay_bookings
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.money import to_money
from app.main import app
from app.models.delhivery_modules import (
    BillingInvoice,
    CodRemittance,
    InvoiceNoteType,
    WeightDispute,
)
from app.models.pickups import (
    CodRemittanceStatus,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
)
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.models.wallet import (
    WalletServiceCategory,
    WalletTransaction,
    WalletTxnStatus,
    WalletTxnType,
)
from app.repositories.delhivery_modules import DelhiveryModulesRepository
from app.repositories.wallet import WalletRepository
from app.services.cod_payout import cod_payout_amount, door_collectible
from app.services.delhivery_modules import (
    WEIGHT_DISPUTE_REFUND_REMARK,
    DelhiveryModulesService,
    document_number_prefix,
    format_document_number,
    gst_state_code_from_gstin,
    gst_state_code_from_state,
    indian_financial_year_label,
    resolve_place_of_supply,
    resolve_supplier_gst_profile,
    split_gst,
)

HEADERS = {"X-Tenant-Slug": "naviera"}
API = settings.API_V1_STR
SHIPMENTS_URL = f"{API}/shipments"
GOODS_VALUE = 700.0
CONCURRENT_HOLD_SECONDS = 0.5


def _payload(
    *,
    cod: bool = False,
    freight_mode: str = "PREPAID",
    add_shipping_to_cod: bool = False,
    pickup_state: str = "MH",
) -> dict:
    tag = uuid.uuid4().hex[:8]
    return {
        "order_reference_id": f"W2A-{tag}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "product_category": "ELECTRONICS",
        "new_pickup_address": {
            "name": f"W2A WH {tag}", "phone": "9000000005", "address_line1": f"Unit {tag}",
            "city": "Pune", "state": pickup_state, "pincode": "411001",
        },
        "new_delivery_address": {
            "name": "W2A Consignee", "phone": "8888888888", "address_line1": "Road 4",
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


async def _tenant() -> Tenant:
    return await app.dependency_overrides[get_tenant_from_header]()


async def _real_user(db_session, role: UserRole) -> User:
    tenant = await _tenant()
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"w2a-{role.value}-{tag}",
        email=f"w2a-{role.value}-{tag}@example.com",
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


@pytest.fixture
async def restore_user_override():
    original = app.dependency_overrides[get_current_active_user]
    yield
    app.dependency_overrides[get_current_active_user] = original


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _book(client: AsyncClient, **kwargs) -> dict:
    if kwargs.get("freight_mode") == "TO_PAY":
        with allow_to_pay_bookings():
            res = await client.post(SHIPMENTS_URL, json=_payload(**kwargs), headers=HEADERS)
    else:
        res = await client.post(SHIPMENTS_URL, json=_payload(**kwargs), headers=HEADERS)
    assert res.status_code == 201, res.text
    return res.json()


async def _set_status(db_session, shipment_id: str, new_status: PickupStatus) -> PickupRequest:
    shipment = await db_session.get(PickupRequest, uuid.UUID(shipment_id))
    shipment.status = new_status
    db_session.add(shipment)
    await db_session.flush()
    return shipment


async def _payment(db_session, shipment_id: str) -> PaymentDetails:
    return (
        await db_session.exec(
            select(PaymentDetails)
            .where(PaymentDetails.pickup_id == uuid.UUID(shipment_id))
            .execution_options(populate_existing=True)
        )
    ).one()


async def _shipment_documents(db_session, shipment_id: str, note_type: str) -> list:
    return list(
        (
            await db_session.exec(
                select(BillingInvoice).where(
                    BillingInvoice.note_type == note_type,
                    BillingInvoice.line_items.contains([{"shipment_id": shipment_id}]),  # type: ignore[attr-defined]
                )
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# 1. S5a: list isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_without_rows_sees_empty_finance_lists(db_session, restore_user_override):
    tenant = await _tenant()
    admin = await app.dependency_overrides[get_current_active_user]()
    db_session.add(
        CodRemittance(
            tenant_id=tenant.id, merchant_user_id=admin.id, remittance_number=f"W2A-R-{uuid.uuid4().hex[:6]}",
            processed_date=date.today(), bank_utr="W2AUTR", total_remittance=10.0, total_orders=1,
        )
    )
    db_session.add(
        BillingInvoice(
            tenant_id=tenant.id, merchant_user_id=admin.id, invoice_number=f"W2A-I-{uuid.uuid4().hex[:6]}",
            invoice_date=date.today(), due_date=date.today(), gst_number="X", billing_address="X",
        )
    )
    db_session.add(
        WeightDispute(tenant_id=tenant.id, merchant_user_id=admin.id, tracking_id=f"W2A-{uuid.uuid4().hex[:8]}")
    )
    await db_session.flush()

    newcomer = await _real_user(db_session, UserRole.customer)
    async with _client() as client:
        _as_user(newcomer)
        for path in ("/remittances", "/invoices", "/disputes/weight-mismatch"):
            res = await client.get(f"{API}{path}", headers=HEADERS)
            assert res.status_code == 200, res.text
            assert res.json() == [], path

        _as_user(admin)
        res = await client.get(f"{API}/remittances", headers=HEADERS)
        assert res.status_code == 200 and len(res.json()) >= 1


# ---------------------------------------------------------------------------
# 2. S5c + M4: weight claims
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_on_other_merchants_awb_is_404(db_session, restore_user_override):
    async with _client() as client:
        owner_ship = await _book(client)  # booked by the admin actor
        res = await client.post(
            f"{SHIPMENTS_URL}/{owner_ship['id']}/audit-weight", json={"audited_weight_kg": 5.0}, headers=HEADERS
        )
        assert res.status_code == 200, res.text

        intruder = await _real_user(db_session, UserRole.customer)
        _as_user(intruder)
        res = await client.post(
            f"{API}/disputes/weight-mismatch/claims", json={"tracking_ids": [owner_ship["tracking_id"]]}, headers=HEADERS
        )
        assert res.status_code == 404, res.text
        res = await client.post(
            f"{API}/disputes/weight-mismatch/claims", json={"tracking_ids": ["NO-SUCH-AWB-W2A"]}, headers=HEADERS
        )
        assert res.status_code == 404, res.text

    dispute = (
        await db_session.exec(select(WeightDispute).where(WeightDispute.tracking_id == owner_ship["tracking_id"]))
    ).one()
    assert dispute.claim_status == "NONE"


@pytest.mark.asyncio
async def test_claim_without_audit_is_400_and_creates_nothing(db_session, restore_user_override):
    merchant = await _real_user(db_session, UserRole.customer)
    async with _client() as client:
        _as_user(merchant)
        ship = await _book(client)
        res = await client.post(
            f"{API}/disputes/weight-mismatch/claims", json={"tracking_ids": [ship["tracking_id"]]}, headers=HEADERS
        )
        assert res.status_code == 400, res.text
        assert "No weight discrepancy recorded" in res.json()["detail"]
    rows = (await db_session.exec(select(WeightDispute).where(WeightDispute.tracking_id == ship["tracking_id"]))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_double_accept_refunds_once_and_resolved_claims_are_final(db_session, restore_user_override):
    async with _client() as client:
        ship = await _book(client)
        res = await client.post(
            f"{SHIPMENTS_URL}/{ship['id']}/audit-weight", json={"audited_weight_kg": 6.0}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        dispute = (
            await db_session.exec(select(WeightDispute).where(WeightDispute.tracking_id == ship["tracking_id"]))
        ).one()
        assert dispute.cost_diff_inr > 0

        res = await client.patch(
            f"{API}/disputes/weight-mismatch/{dispute.id}/resolve", json={"claim_status": "ACCEPTED"}, headers=HEADERS
        )
        assert res.status_code == 400, "cannot accept before a claim is raised"

        res = await client.post(  # staff raises on the merchant's behalf
            f"{API}/disputes/weight-mismatch/claims", json={"tracking_ids": [ship["tracking_id"]]}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        assert res.json()[0]["claim_status"] == "CLAIM_RAISED"

        res = await client.patch(
            f"{API}/disputes/weight-mismatch/{dispute.id}/resolve", json={"claim_status": "ACCEPTED"}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        res = await client.patch(
            f"{API}/disputes/weight-mismatch/{dispute.id}/resolve", json={"claim_status": "ACCEPTED"}, headers=HEADERS
        )
        assert res.status_code == 400, res.text
        res = await client.post(
            f"{API}/disputes/weight-mismatch/claims", json={"tracking_ids": [ship["tracking_id"]]}, headers=HEADERS
        )
        assert res.status_code == 400, res.text
        res = await client.patch(
            f"{API}/disputes/weight-mismatch/{dispute.id}/resolve", json={"claim_status": "REJECTED"}, headers=HEADERS
        )
        assert res.status_code == 400, res.text

    refunds = (
        await db_session.exec(
            select(WalletTransaction).where(
                WalletTransaction.shipment_id == uuid.UUID(ship["id"]),
                WalletTransaction.txn_type == WalletTxnType.REFUND.value,
                WalletTransaction.remarks.startswith(WEIGHT_DISPUTE_REFUND_REMARK),  # type: ignore[attr-defined]
            )
        )
    ).all()
    assert len(refunds) == 1
    assert len(await _shipment_documents(db_session, ship["id"], InvoiceNoteType.CREDIT_NOTE.value)) == 1


# ---------------------------------------------------------------------------
# 3. M2 + M3: COD remittance batches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remittance_batch_is_per_merchant_and_goods_only(db_session, restore_user_override):
    merchant = await _real_user(db_session, UserRole.customer)
    other = await _real_user(db_session, UserRole.customer)
    admin = await app.dependency_overrides[get_current_active_user]()
    tenant = await _tenant()
    async with _client() as client:
        _as_user(merchant)
        prepaid = await _book(client, cod=True)
        to_pay = await _book(client, cod=True, freight_mode="TO_PAY", add_shipping_to_cod=True)
        rto = await _book(client, cod=True)
        settled = await _book(client, cod=True)
        undelivered = await _book(client, cod=True)
        _as_user(other)
        foreign = await _book(client, cod=True)

        for ship in (prepaid, to_pay, rto, settled, foreign):
            await _set_status(db_session, ship["id"], PickupStatus.COMPLETED)
        db_session.add(
            ShipmentActivity(
                pickup_id=uuid.UUID(rto["id"]), user_id=admin.id,
                diff={"status": {"old": "IN_TRANSIT", "new": PickupStatus.RTO_INITIATED.value}},
            )
        )
        wallet = await WalletRepository(db_session).get_or_create_wallet(
            user_id=merchant.id, tenant_id=tenant.id, for_update=False
        )
        db_session.add(
            WalletTransaction(
                wallet_id=wallet.id, tenant_id=tenant.id, user_id=merchant.id,
                shipment_id=uuid.UUID(settled["id"]), txn_type=WalletTxnType.COD_SETTLEMENT,
                service_category=WalletServiceCategory.B2C, amount=GOODS_VALUE,
                receipt_number=f"W2A-COD-{uuid.uuid4().hex[:6]}", status=WalletTxnStatus.COMPLETED,
            )
        )
        await db_session.flush()

        _as_user(admin)
        res = await client.post(
            f"{API}/remittances", json={"bank_utr": "W2AUTR1", "expected_total": GOODS_VALUE}, headers=HEADERS
        )
        assert res.status_code == 400, "a batch must name one merchant"
        res = await client.post(
            f"{API}/remittances",
            json={
                "bank_utr": "W2AUTR2",
                "shipment_ids": [prepaid["id"], foreign["id"]],
                "expected_total": 2 * GOODS_VALUE,
            },
            headers=HEADERS,
        )
        assert res.status_code == 400, res.text
        res = await client.post(
            f"{API}/remittances",
            json={
                "bank_utr": "W2AUTR3",
                "merchant_user_id": str(merchant.id),
                "shipment_ids": [rto["id"]],
                "expected_total": GOODS_VALUE,
            },
            headers=HEADERS,
        )
        assert res.status_code == 400, "RTO shipments are never remitted"

        res = await client.post(
            f"{API}/remittances",
            json={
                "bank_utr": "W2AUTR4",
                "merchant_user_id": str(merchant.id),
                "expected_total": 2 * GOODS_VALUE,
            },
            headers=HEADERS,
        )
        assert res.status_code == 400, "a batch must tick shipment_ids explicitly"

        preview = await client.get(
            f"{API}/remittances/pending",
            params={"merchant_user_id": str(merchant.id)},
            headers=HEADERS,
        )
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()
        assert {line["shipment_id"] for line in preview_data["lines"]} == {prepaid["id"], to_pay["id"]}
        assert preview_data["total"] == pytest.approx(2 * GOODS_VALUE)
        assert preview_data["payout_blocked_reason"] is not None

        # A-05: while the merchant's wallet is negative, bank-UTR COD payout is held (409).
        held = await client.post(
            f"{API}/remittances",
            json={
                "bank_utr": "W2AUTR4",
                "merchant_user_id": str(merchant.id),
                "shipment_ids": [prepaid["id"], to_pay["id"]],
                "expected_total": 2 * GOODS_VALUE,
            },
            headers=HEADERS,
        )
        assert held.status_code == 409, held.text

        # Reflect the settled COD credit on the wallet balance so it is >= ₹0.
        wallet.balance = float(to_money(to_money(wallet.balance) + to_money(GOODS_VALUE)))
        db_session.add(wallet)
        await db_session.flush()

        res = await client.post(
            f"{API}/remittances",
            json={
                "bank_utr": "W2AUTR4",
                "merchant_user_id": str(merchant.id),
                "shipment_ids": [prepaid["id"], to_pay["id"]],
                "expected_total": 2 * GOODS_VALUE,
            },
            headers=HEADERS,
        )
        assert res.status_code == 201, res.text
        batch = res.json()

        res = await client.post(
            f"{API}/remittances",
            json={
                "bank_utr": "W2AUTR5",
                "merchant_user_id": str(merchant.id),
                "shipment_ids": [prepaid["id"], to_pay["id"]],
                "expected_total": 2 * GOODS_VALUE,
            },
            headers=HEADERS,
        )
        assert res.status_code == 400, "nothing left to remit"

    lines = {line["shipment_id"]: line["amount_collected"] for line in batch["shipment_breakdown"]}
    assert set(lines) == {prepaid["id"], to_pay["id"]}
    assert batch["merchant_user_id"] == str(merchant.id)
    to_pay_payment = await _payment(db_session, to_pay["id"])
    # B7 / M-B3: a TO_PAY booking keeps the goods in `cod_amount` and the freight in
    # `freight_collectible`; the rider collects both at the door, the merchant gets the goods.
    to_pay_freight = to_money(to_pay_payment.total_logistics_cost)
    assert to_money(to_pay_payment.cod_amount) == to_money(GOODS_VALUE)
    assert to_money(to_pay_payment.freight_collectible) == to_pay_freight
    assert door_collectible(to_pay_payment) == to_money(GOODS_VALUE) + to_pay_freight
    assert lines[to_pay["id"]] == cod_payout_amount(to_pay_payment) == GOODS_VALUE
    assert lines[prepaid["id"]] == GOODS_VALUE
    assert batch["total_remittance"] == pytest.approx(sum(lines.values()))
    assert batch["total_orders"] == 2

    for ship in (prepaid, to_pay):
        assert (await _payment(db_session, ship["id"])).cod_remittance_status == CodRemittanceStatus.REMITTED
    for ship in (rto, settled, undelivered, foreign):
        status = (await _payment(db_session, ship["id"])).cod_remittance_status
        assert status != CodRemittanceStatus.REMITTED, ship["id"]


# ---------------------------------------------------------------------------
# 4. M5: GST split and numbering
# ---------------------------------------------------------------------------


def test_gst_split_intra_vs_inter_state_and_report_example():
    intra = split_gst(total=94.40, tax_total=14.40, supplier_state_code="06", place_of_supply="06")
    assert (intra.taxable_value, intra.cgst, intra.sgst, intra.igst) == (80.0, 7.20, 7.20, 0.0)
    assert intra.is_intra_state and intra.tax_rate_percent == 18.0
    inter = split_gst(total=94.40, tax_total=14.40, supplier_state_code="06", place_of_supply="27")
    assert (inter.taxable_value, inter.cgst, inter.sgst, inter.igst) == (80.0, 0.0, 0.0, 14.40)
    unknown_supplier = split_gst(total=94.40, tax_total=14.40, supplier_state_code=None, place_of_supply=None)
    assert unknown_supplier.igst == 14.40

    assert gst_state_code_from_gstin("06AAECL2138H1ZQ") == "06"
    assert gst_state_code_from_gstin("Not Configured") is None
    assert gst_state_code_from_state("Haryana") == "06"
    assert gst_state_code_from_state("MH") == "27"
    assert gst_state_code_from_state("Tamil Nadu") == "33"
    assert gst_state_code_from_state("Jammu & Kashmir") == "01"
    assert resolve_place_of_supply("06", "27AAAAA0000A1Z5", "Haryana") == "27"
    assert resolve_place_of_supply("06", None, "Haryana") == "06"
    assert resolve_place_of_supply("06", None, None) == "06"


def test_shipment_tax_uses_engine_gst_not_total_minus_base():
    payment = PaymentDetails(
        pickup_id=uuid.uuid4(), base_freight=50.0, tax_amount=14.40, total_logistics_cost=94.40,
        pricing_breakdown={"subtotal": 80.0},
    )
    tenant = Tenant(name="T", slug="t", settings={})
    tax = DelhiveryModulesService._shipment_tax_component(tenant, payment, 94.40, None)
    assert tax == 14.40  # never 94.40 - 50 = 44.40
    partial = DelhiveryModulesService._shipment_tax_component(tenant, payment, 11.80, 11.80)
    assert partial == 1.80  # credit / debit note backs out GST at the applied 18 %


def test_document_number_format_and_financial_year():
    assert indian_financial_year_label(date(2026, 10, 17)) == "2627"
    assert indian_financial_year_label(date(2027, 3, 31)) == "2627"
    assert indian_financial_year_label(date(2027, 4, 1)) == "2728"
    custom = Tenant(name="X", slug="x", settings={"company": {"invoice_prefix": "ls-in/x"}})
    assert document_number_prefix(custom, "2627", InvoiceNoteType.INVOICE.value) == "LSIN2627I"


@pytest.mark.parametrize(
    ("note_type", "expected"),
    [
        (InvoiceNoteType.INVOICE.value, "LOGI2627I000001"),
        (InvoiceNoteType.CREDIT_NOTE.value, "LOGI2627C000001"),
        (InvoiceNoteType.DEBIT_NOTE.value, "LOGI2627D000001"),
    ],
)
def test_document_number_is_gst_rule_46_compliant(note_type, expected):
    tenant = Tenant(name="Logi", slug="logismart", settings={})
    number = format_document_number(document_number_prefix(tenant, "2627", note_type), 1)
    assert number == expected
    assert len(number) <= 16 and number.isalnum()
    worst = format_document_number(document_number_prefix(tenant, "2627", note_type), 999999)
    assert len(worst) == 15
    with pytest.raises(HTTPException) as overflow:
        format_document_number("TOOLONGPREFIX", 1)
    assert overflow.value.status_code == 500


@pytest.mark.asyncio
async def test_booking_invoices_use_engine_gst_tenant_supplier_and_sequential_numbers(db_session):
    tenant = await db_session.get(Tenant, (await _tenant()).id)
    supplier = resolve_supplier_gst_profile(tenant)
    async with _client() as client:
        first = await _book(client, pickup_state="Haryana")
        second = await _book(client, pickup_state="Maharashtra")
        pdf = await client.get(f"{SHIPMENTS_URL}/{first['id']}/invoice-pdf", headers=HEADERS)
        assert pdf.status_code == 200, pdf.text
        assert pdf.content.startswith(b"%PDF")

    inv_first = (await _shipment_documents(db_session, first["id"], InvoiceNoteType.INVOICE.value))
    inv_second = (await _shipment_documents(db_session, second["id"], InvoiceNoteType.INVOICE.value))
    assert len(inv_first) == 1 and len(inv_second) == 1, "the PDF reuses the register row"
    a, b = inv_first[0], inv_second[0]

    payment = await _payment(db_session, first["id"])
    assert a.freight_amount == pytest.approx(payment.total_logistics_cost - payment.tax_amount)
    assert a.cgst_amount + a.sgst_amount + a.igst_amount == pytest.approx(payment.tax_amount)
    assert a.total_amount == pytest.approx(payment.total_logistics_cost)
    assert a.gst_number == supplier.gstin
    expected_intra = supplier.state_code == "06"
    assert (a.igst_amount == 0) == expected_intra
    assert (b.igst_amount == 0) == (supplier.state_code == "27")

    prefix = document_number_prefix(tenant, indian_financial_year_label(a.invoice_date), "INVOICE")
    assert a.invoice_number.startswith(prefix) and b.invoice_number.startswith(prefix)
    assert len(a.invoice_number) <= 16 and a.invoice_number.isalnum()
    assert int(b.invoice_number[-6:]) == int(a.invoice_number[-6:]) + 1


@pytest.mark.asyncio
async def test_sequential_numbering_is_unique_under_concurrent_allocations():
    """Two independent transactions allocate from the same (test-only) series at once."""
    seed = await _tenant()
    admin = await app.dependency_overrides[get_current_active_user]()
    financial_year = f"T{uuid.uuid4().hex[:3].upper()}"
    number_prefix = f"Z{financial_year}I"  # test-only series, never a real prefix
    created_ids: list = []

    async def _allocate_and_insert() -> str:
        async with AsyncSessionLocal() as session:
            repo = DelhiveryModulesRepository(session)
            serial = await repo.allocate_document_sequence(
                tenant_id=seed.id, financial_year=financial_year,
                note_type=InvoiceNoteType.INVOICE.value, number_prefix=number_prefix,
            )
            invoice = BillingInvoice(
                tenant_id=seed.id, merchant_user_id=admin.id,
                invoice_number=format_document_number(number_prefix, serial),
                invoice_date=date.today(), due_date=date.today(), gst_number="TEST", billing_address="TEST",
            )
            session.add(invoice)
            await session.flush()
            created_ids.append(invoice.id)
            await asyncio.sleep(CONCURRENT_HOLD_SECONDS)  # keep the lock while the other waits
            await session.commit()
            return invoice.invoice_number

    try:
        numbers = await asyncio.gather(_allocate_and_insert(), _allocate_and_insert())
        assert sorted(numbers) == [f"{number_prefix}000001", f"{number_prefix}000002"]
    finally:
        async with AsyncSessionLocal() as cleanup:
            for invoice_id in created_ids:
                row = await cleanup.get(BillingInvoice, invoice_id)
                if row is not None:
                    await cleanup.delete(row)
            await cleanup.commit()
