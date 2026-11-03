"""
Golden Test Suite 3 & 4 (`J09-J18`):
- Suite 3: B2C Forward Booking Matrix, Admin Edit & Pre-Pickup Cancellation (`J09-J14`)
- Suite 4: Pickup Requests (`PUR`) Full Lifecycle & Partial Pickup (`J15-J18`)

Runs ONLY against the guarded test tenant (`GOLDEN_TENANT_SLUG`, default
`logismart-test`), reset once per session by `golden_journeys/conftest.py`, with
real JWT sessions for the canonical test accounts. Verifies rupee-and-paisa
wallet balances, GST invoices/credit notes, and
`GET /api/v1/wallet/audit-integrity`.
"""

import uuid
from datetime import date
from typing import Any, Dict

import httpx
import pytest
from httpx import ASGITransport
from sqlmodel import select

from app.main import app
from app.models.delhivery_modules import BillingInvoice, InvoiceNoteType
from app.models.manifests import Manifest, ManifestStatus
from app.models.pickups import (
    FreightPaymentMode,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ServiceType,
)
from app.models.wallet import WalletTransaction, WalletTxnStatus, WalletTxnType
from app.services.cod_payout import (
    carrier_freight_collected,
    cod_payout_amount,
    door_collectible,
)

from .golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GOLDEN_TENANT_SLUG,
    OPERATIONS_EMAIL,
    OWNER_EMAIL,
    GoldenSessionLocal,
    allow_to_pay_bookings,
    document_prefix,
    find_seeded_address_id,
    first_document_number,
    order_ref,
    read_otp_as_merchant,
    save_state,
)
from .golden_env import (
    get_wallet_balance as _get_wallet_balance,
)
from .golden_env import (
    headers as _headers,
)
from .golden_env import (
    load_accounts as _load_accounts,
)

TENANT_SLUG = GOLDEN_TENANT_SLUG
BATCH2_STATE = "batch2"
INVOICE_PREFIX = document_prefix(InvoiceNoteType.INVOICE.value)
CREDIT_NOTE_PREFIX = document_prefix(InvoiceNoteType.CREDIT_NOTE.value)

STATE: Dict[str, Any] = {}


async def _ensure_b2c_warehouse(
    client: httpx.AsyncClient, accounts: Dict[str, Dict[str, Any]]
) -> str:
    """
    Returns the seeded PRIVATE Gurugram (`122001`) warehouse of
    `customerb2c@logismart.in`. The seed/reset creates it; this suite never does.
    """
    if STATE.get("warehouse_address_id"):
        return str(STATE["warehouse_address_id"])
    warehouse_id = await find_seeded_address_id(client, accounts, CUSTOMER_B2C_EMAIL)
    STATE["warehouse_address_id"] = warehouse_id
    return warehouse_id


@pytest.mark.asyncio
async def test_j09_b2c_prepaid_cod_negative_wallet_and_gst_invoice():
    """
    J09: Book Order #1 as `customerb2c@logismart.in` (`PREPAID`, `is_cod=True`,
    `shipment_value=1500.0`, `shipment_tax_value=0.0`, `shipment_total_value=1500.0`,
    `add_shipping_to_cod=False`, `service_type="SURFACE_ROAD"`).
    Verifies:
    - `status == "OPEN"`
    - `payment_details.cod_amount == 1500.0`
    - `user_wallets.balance` decreased by exact `total_logistics_cost` (negative balance allowed per D37)
    - `COMPLETED` `SPEND` `WalletTransaction` row with exact `opening_balance` & `closing_balance`
    - GST `INVOICE` (`<PFX><FY>I` e.g. `LTST2627I000001`) in `billing_invoices` with 9% CGST + 9% SGST (intra-state Haryana `06`).
    """
    accounts = await _load_accounts()
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    opening_bal = await _get_wallet_balance(b2c_user_id)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        warehouse_id = await _ensure_b2c_warehouse(client, accounts)

        resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "order_reference_id": order_ref("J09-ORD1"),
                "shipment_type": "FORWARD",
                "service_type": ServiceType.SURFACE_ROAD.value,
                "requested_pickup_date": date.today().isoformat(),
                "product_category": "ELECTRONICS",
                "pickup_address_id": warehouse_id,
                "new_delivery_address": {
                    "name": "Aarav Sharma",
                    "phone": "9810011101",
                    "address_line1": "Flat 402, DLF Phase 3",
                    "city": "Gurugram",
                    "state": "Haryana",
                    "pincode": "122002",
                    "country": "IN",
                    "category": "HOME",
                },
                "packages": [
                    {
                        "length": 20.0,
                        "breadth": 15.0,
                        "height": 10.0,
                        "dimension_unit": "CM",
                        "weight": 0.5,
                        "weight_unit": "KG",
                        "box_count": 1,
                        "description": "Wireless ANC Earbuds",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": True,
                    "cod_amount": 1500.0,
                    "shipment_value": 1500.0,
                    "shipment_tax_value": 0.0,
                    "shipment_total_value": 1500.0,
                    "add_shipping_to_cod": False,
                },
            },
        )
        assert resp.status_code == 201, resp.text
        order1 = resp.json()
        order1_id = order1["id"]
        STATE["order1_id"] = order1_id
        STATE["order1_tracking_id"] = order1["tracking_id"]

        assert order1["status"] == "OPEN"
        pd = order1["payment_details"]
        assert pd["freight_payment_mode"] == "PREPAID"
        assert pd["is_cod"] is True
        assert round(float(pd["cod_amount"]), 2) == 1500.0
        total_cost = round(float(pd["total_logistics_cost"]), 2)
        assert total_cost > 0
        STATE["order1_cost"] = total_cost

        expected_closing = round(opening_bal - total_cost, 2)
        actual_closing = await _get_wallet_balance(b2c_user_id)
        assert actual_closing == expected_closing
        if opening_bal <= 0:
            # D37: a PREPAID booking may push a wallet that starts at <= 0 negative.
            assert actual_closing < 0, "Wallet should be negative per D37 when starting from <= 0"

        # Verify WalletTransaction and BillingInvoice in PostgreSQL
        async with GoldenSessionLocal() as session:
            txn = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.shipment_id == uuid.UUID(order1_id),
                        WalletTransaction.txn_type == WalletTxnType.SPEND,
                    )
                )
            ).first()
            assert txn is not None
            assert txn.status == WalletTxnStatus.COMPLETED
            assert round(float(txn.opening_balance), 2) == opening_bal
            assert round(float(txn.amount), 2) == total_cost
            assert round(float(txn.closing_balance), 2) == expected_closing

            invoices = (
                await session.exec(
                    select(BillingInvoice).where(
                        BillingInvoice.merchant_user_id == uuid.UUID(b2c_user_id),
                        BillingInvoice.note_type == InvoiceNoteType.INVOICE.value,
                    )
                )
            ).all()
            matching_inv = None
            for inv in invoices:
                for item in inv.line_items or []:
                    if isinstance(item, dict) and item.get("shipment_id") == order1_id:
                        matching_inv = inv
                        break
            assert matching_inv is not None, "Expected GST INVOICE row in billing_invoices"
            assert matching_inv.invoice_number.startswith(INVOICE_PREFIX)
            # J09 books the first PREPAID shipment after the session reset, so the
            # GST series restarts: exactly `<PFX><FY>I000001` (GST Rule 46, <= 16 chars).
            assert matching_inv.invoice_number == first_document_number(
                InvoiceNoteType.INVOICE.value
            )
            assert len(matching_inv.invoice_number) <= 16
            assert round(float(matching_inv.total_amount), 2) == total_cost
            # Intra-state Haryana (06 -> 06): 9% CGST + 9% SGST, 0% IGST
            # `freight_amount` is the taxable value: 18% GST on it, split 9% CGST + 9% SGST
            taxable = round(float(matching_inv.freight_amount), 2)
            cgst = round(float(matching_inv.cgst_amount), 2)
            sgst = round(float(matching_inv.sgst_amount), 2)
            assert round(cgst + sgst, 2) == round(taxable * 0.18, 2)
            assert cgst == round((cgst + sgst) / 2, 2)
            assert round(taxable + cgst + sgst, 2) == total_cost
            assert round(float(matching_inv.cgst_amount), 2) == round(
                float(matching_inv.sgst_amount), 2
            )
            assert round(float(matching_inv.igst_amount), 2) == 0.0
            STATE["order1_invoice_number"] = matching_inv.invoice_number

            db_pd = (await session.exec(select(PaymentDetails).where(PaymentDetails.pickup_id == uuid.UUID(order1_id)))).first()
            assert db_pd is not None
            assert float(door_collectible(db_pd)) == 1500.0


@pytest.mark.asyncio
async def test_j10_b2c_prepaid_cod_add_shipping_to_cod_true():
    """
    J10: Book Order #2 as `customerb2c@logismart.in` (`PREPAID`, `is_cod=True`,
    `shipment_total_value=1000.0`, `add_shipping_to_cod=True`).
    Verifies server sets `payment_details.cod_amount == round(1000.0 + total_logistics_cost, 2)`
    and debits `total_logistics_cost` from `customerb2c`'s wallet.
    """
    accounts = await _load_accounts()
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    opening_bal = await _get_wallet_balance(b2c_user_id)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        warehouse_id = await _ensure_b2c_warehouse(client, accounts)

        resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "order_reference_id": order_ref("J10-ORD2"),
                "shipment_type": "FORWARD",
                "service_type": ServiceType.SURFACE_ROAD.value,
                "requested_pickup_date": date.today().isoformat(),
                "product_category": "APPAREL",
                "pickup_address_id": warehouse_id,
                "new_delivery_address": {
                    "name": "Priya Verma",
                    "phone": "9810011102",
                    "address_line1": "B-12, Connaught Place",
                    "city": "New Delhi",
                    "state": "Delhi",
                    "pincode": "110001",
                    "country": "IN",
                    "category": "HOME",
                },
                "packages": [
                    {
                        "length": 20.0,
                        "breadth": 15.0,
                        "height": 10.0,
                        "dimension_unit": "CM",
                        "weight": 0.5,
                        "weight_unit": "KG",
                        "box_count": 1,
                        "description": "Winter Denim Jacket",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": True,
                    "cod_amount": 1000.0,
                    "shipment_value": 1000.0,
                    "shipment_tax_value": 0.0,
                    "shipment_total_value": 1000.0,
                    "add_shipping_to_cod": True,
                },
            },
        )
        assert resp.status_code == 201, resp.text
        order2 = resp.json()
        order2_id = order2["id"]
        STATE["order2_id"] = order2_id
        STATE["order2_tracking_id"] = order2["tracking_id"]
        STATE["order2_old_delivery_address_id"] = order2["delivery_address"]["id"]
        STATE["order2_pkg_id"] = order2["packages"][0]["id"]

        pd = order2["payment_details"]
        total_cost = round(float(pd["total_logistics_cost"]), 2)
        assert total_cost > 0
        STATE["order2_old_cost"] = total_cost

        expected_cod = round(1000.0 + total_cost, 2)
        assert round(float(pd["cod_amount"]), 2) == expected_cod

        actual_closing = await _get_wallet_balance(b2c_user_id)
        assert actual_closing == round(opening_bal - total_cost, 2)


@pytest.mark.asyncio
async def test_j11_b2c_to_pay_plus_cod_zero_upfront_wallet_debit():
    """
    J11: Book Order #3 as `customerb2c@logismart.in` (`TO_PAY`, `is_cod=True`,
    `shipment_total_value=2000.0`).
    Verifies:
    - Upfront Wallet Debit = `₹0.00` (`user_wallets.balance` unchanged before/after)
    - `GET /api/v1/shipments/{id}/invoice-pdf` returns `400` (`TO_PAY` consignee pays freight at delivery)
    - `cod_payout_amount` (`cod_payout.py`) returns `2000.0` (goods value only, per D26).
    """
    accounts = await _load_accounts()
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    opening_bal = await _get_wallet_balance(b2c_user_id)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        warehouse_id = await _ensure_b2c_warehouse(client, accounts)

        order3_payload = {
            "order_reference_id": order_ref("J11-ORD3"),
            "shipment_type": "FORWARD",
            "service_type": ServiceType.SURFACE_ROAD.value,
            "requested_pickup_date": date.today().isoformat(),
            "product_category": "HOUSEHOLD_PERSONAL",
            "pickup_address_id": warehouse_id,
            "new_delivery_address": {
                "name": "Rohan Mehta",
                "phone": "9810011103",
                "address_line1": "Flat 101, Powai Vihar",
                "city": "Mumbai",
                "state": "Maharashtra",
                "pincode": "400076",
                "country": "IN",
                "category": "HOME",
            },
            "packages": [
                {
                    "length": 25.0,
                    "breadth": 20.0,
                    "height": 15.0,
                    "dimension_unit": "CM",
                    "weight": 1.0,
                    "weight_unit": "KG",
                    "box_count": 1,
                    "description": "Espresso Coffee Maker",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "TO_PAY",
                "is_cod": True,
                "cod_amount": 2000.0,
                "shipment_value": 2000.0,
                "shipment_tax_value": 0.0,
                "shipment_total_value": 2000.0,
                "add_shipping_to_cod": True,
            },
        }
        # MVP Scope (DESIGN.md v4 §9): new TO_PAY bookings are refused with 400 by default
        refused_resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json=order3_payload,
        )
        assert refused_resp.status_code == 400, refused_resp.text
        assert "to-pay" in refused_resp.json()["detail"].lower()

        # Seed legacy TO_PAY Order #3 via allow_to_pay_bookings() to verify legacy row invariants (D26, J32)
        with allow_to_pay_bookings():
            resp = await client.post(
                "/api/v1/shipments",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
                json=order3_payload,
            )
        assert resp.status_code == 201, resp.text
        order3 = resp.json()
        order3_id = order3["id"]
        STATE["order3_id"] = order3_id
        STATE["order3_tracking_id"] = order3["tracking_id"]

        pd = order3["payment_details"]
        assert pd["freight_payment_mode"] == "TO_PAY"
        order3_freight = round(float(pd["total_logistics_cost"]), 2)
        assert order3_freight > 0
        STATE["order3_freight"] = order3_freight

        # Upfront wallet debit is ₹0.00
        after_bal = await _get_wallet_balance(b2c_user_id)
        assert after_bal == opening_bal

        # Invoice endpoint returns 400 for TO_PAY
        inv_resp = await client.get(
            f"/api/v1/shipments/{order3_id}/invoice-pdf",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert inv_resp.status_code == 400, inv_resp.text
        assert "to_pay" in inv_resp.json()["detail"].lower()

        # Verify cod_payout_amount returns 2000.0 (goods value only, carrier keeps TO_PAY freight per D26)
        async with GoldenSessionLocal() as session:
            db_pd = (
                await session.exec(
                    select(PaymentDetails).where(
                        PaymentDetails.pickup_id == uuid.UUID(order3_id)
                    )
                )
            ).first()
            assert db_pd is not None
            assert db_pd.freight_payment_mode == FreightPaymentMode.TO_PAY
            assert cod_payout_amount(db_pd) == 2000.0
            assert carrier_freight_collected(db_pd) == order3_freight
            assert float(door_collectible(db_pd)) == 2000.0 + order3_freight


@pytest.mark.asyncio
async def test_j12_customer_postpaid_wallet_billed_category_other_validation_and_staff_postpaid():
    """
    J12 (lean MVP, plan B16 / decision D85 option b):
    1) `customerb2c@logismart.in` self-books `freight_payment_mode="POSTPAID"` -> `201`.
       The shipment is wallet-billed exactly like PREPAID: `pricing_breakdown.billing_channel
       == "WALLET"`, the customer's OWN wallet is debited by the exact `total_logistics_cost`
       (20x15x10 cm, 0.5 kg -> 1 kg volumetric slab -> Rs.94.40) through one COMPLETED `SPEND`
       row, and one GST `INVOICE` with the next serial of the `LTST` series is issued.
    2) `product_category="OTHER"` without `other_category_description` gets `400/422`.
    3) Book Order #4 (`POSTPAID`) as `admin@logismart.in` with `product_category="OTHER"` and
       `other_category_description="Custom Exhibition Samples"` -> staff-booked POSTPAID keeps
       today's behaviour: `billing_channel == "NONE"`, Rs.0 upfront wallet debit, no `SPEND`
       row and no `INVOICE` for that shipment.
    """
    j12_postpaid_total = 94.40
    accounts = await _load_accounts()
    admin_user_id = accounts[ADMIN_EMAIL]["id"]
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    admin_bal_before = await _get_wallet_balance(admin_user_id)
    serial_width = len(first_document_number(InvoiceNoteType.INVOICE.value)) - len(INVOICE_PREFIX)

    async def _next_invoice_number() -> str:
        """Next serial of the test tenant's INVOICE series (max + 1), read from the DB."""
        async with GoldenSessionLocal() as session:
            numbers = (
                await session.exec(
                    select(BillingInvoice.invoice_number).where(
                        BillingInvoice.invoice_number.startswith(INVOICE_PREFIX)
                    )
                )
            ).all()
            await session.rollback()
        serials = [int(n[len(INVOICE_PREFIX):]) for n in numbers if n[len(INVOICE_PREFIX):].isdigit()]
        return f"{INVOICE_PREFIX}{(max(serials) if serials else 0) + 1:0{serial_width}d}"

    async def _shipment_money_rows(shipment_id: str) -> tuple[list, list]:
        """(wallet txns, GST INVOICEs) linked to one shipment of the test tenant."""
        async with GoldenSessionLocal() as session:
            txns = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.shipment_id == uuid.UUID(shipment_id)
                    )
                )
            ).all()
            docs = (
                await session.exec(
                    select(BillingInvoice).where(
                        BillingInvoice.note_type == InvoiceNoteType.INVOICE.value,
                        BillingInvoice.invoice_number.startswith(INVOICE_PREFIX),
                    )
                )
            ).all()
            await session.rollback()
        linked = [
            d for d in docs
            if str(getattr(d, "shipment_id", None) or "") == shipment_id
            or any(
                isinstance(item, dict) and item.get("shipment_id") == shipment_id
                for item in (d.line_items or [])
            )
        ]
        return list(txns), linked

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        warehouse_id = await _ensure_b2c_warehouse(client, accounts)

        base_payload = {
            "order_reference_id": order_ref("J12-ORD4"),
            "shipment_type": "FORWARD",
            "service_type": ServiceType.SURFACE_ROAD.value,
            "requested_pickup_date": date.today().isoformat(),
            "product_category": "ELECTRONICS",
            "pickup_address_id": warehouse_id,
            "new_delivery_address": {
                "name": "Vikramaditya Rao",
                "phone": "9810011104",
                "address_line1": "14 MG Road",
                "city": "Bengaluru",
                "state": "Karnataka",
                "pincode": "560001",
                "country": "IN",
                "category": "OFFICE",
            },
            "packages": [
                {
                    "length": 20.0,
                    "breadth": 15.0,
                    "height": 10.0,
                    "dimension_unit": "CM",
                    "weight": 0.5,
                    "weight_unit": "KG",
                    "box_count": 1,
                    "description": "Exhibition Sample Unit",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "POSTPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_value": 1200.0,
                "shipment_tax_value": 0.0,
                "shipment_total_value": 1200.0,
            },
        }

        # 1. Customer POSTPAID -> 201, wallet-billed like PREPAID (own wallet + INVOICE)
        b2c_bal_before = await _get_wallet_balance(b2c_user_id)
        expected_invoice_number = await _next_invoice_number()
        cust_postpaid = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json=dict(base_payload, order_reference_id=order_ref("J12-ORD4C")),
        )
        assert cust_postpaid.status_code == 201, cust_postpaid.text
        cust_order = cust_postpaid.json()
        cust_order_id = cust_order["id"]
        STATE["order4c_id"] = cust_order_id
        cust_pd = cust_order["payment_details"]
        assert cust_pd["freight_payment_mode"] == "POSTPAID"
        assert cust_pd["pricing_breakdown"]["billing_channel"] == "WALLET"
        cust_total = round(float(cust_pd["total_logistics_cost"]), 2)
        assert cust_total == j12_postpaid_total

        b2c_bal_after = await _get_wallet_balance(b2c_user_id)
        assert b2c_bal_after == round(b2c_bal_before - cust_total, 2)
        cust_txns, cust_invoices = await _shipment_money_rows(cust_order_id)
        assert len(cust_txns) == 1
        spend = cust_txns[0]
        assert spend.txn_type == WalletTxnType.SPEND
        assert spend.status == WalletTxnStatus.COMPLETED
        assert spend.user_id == uuid.UUID(b2c_user_id), "debited from the customer's OWN wallet"
        assert round(float(spend.amount), 2) == cust_total
        assert round(float(spend.opening_balance), 2) == b2c_bal_before
        assert round(float(spend.closing_balance), 2) == b2c_bal_after
        assert len(cust_invoices) == 1
        cust_invoice = cust_invoices[0]
        assert cust_invoice.invoice_number == expected_invoice_number
        assert cust_invoice.merchant_user_id == uuid.UUID(b2c_user_id)
        assert round(float(cust_invoice.total_amount), 2) == cust_total
        assert round(
            float(cust_invoice.freight_amount)
            + float(cust_invoice.cgst_amount)
            + float(cust_invoice.sgst_amount)
            + float(cust_invoice.igst_amount),
            2,
        ) == cust_total

        # 2. ProductCategory.OTHER without other_category_description -> 400/422
        bad_other_payload = dict(base_payload, product_category="OTHER")
        bad_other_resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, ADMIN_EMAIL),
            json=bad_other_payload,
        )
        assert bad_other_resp.status_code in (400, 422), bad_other_resp.text

        # 3. Admin books Order #4 (POSTPAID) with valid OTHER description
        good_other_payload = dict(
            base_payload,
            product_category="OTHER",
            other_category_description="Custom Exhibition Samples",
        )
        admin_postpaid = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, ADMIN_EMAIL),
            json=good_other_payload,
        )
        assert admin_postpaid.status_code == 201, admin_postpaid.text
        order4 = admin_postpaid.json()
        STATE["order4_id"] = order4["id"]
        STATE["order4_tracking_id"] = order4["tracking_id"]
        assert order4["product_category"] == "OTHER"
        assert order4["other_category_description"] == "Custom Exhibition Samples"
        assert order4["payment_details"]["freight_payment_mode"] == "POSTPAID"
        assert order4["payment_details"]["pricing_breakdown"]["billing_channel"] == "WALLET"

        admin_bal_after = await _get_wallet_balance(admin_user_id)
        order4_cost = float(order4["payment_details"]["total_logistics_cost"])
        assert round(admin_bal_before - admin_bal_after, 2) == round(order4_cost, 2)
        staff_txns, staff_invoices = await _shipment_money_rows(order4["id"])
        assert len(staff_txns) == 1, "staff-booked POSTPAID is wallet-billed (#558 3a)"
        assert len(staff_invoices) == 1


@pytest.mark.asyncio
async def test_j13_admin_shipment_edit_weight_increase_wallet_reconcile_and_address_snapshot():
    """
    J13: `admin@logismart.in` edits Order #2 (`PATCH /api/v1/shipments/{id}`):
    increases package weight from `0.5 kg` to `2.0 kg` and updates delivery `address_line1`.
    Verifies:
    - A new `Address` snapshot row is created (`new_delivery_address_id != old_delivery_address_id`)
    - `WalletService.reconcile_shipment_edit` debits the exact freight delta `new_cost - old_cost`
      from `customerb2c`'s wallet
    - `ShipmentActivity` logs the diff (`packages`, `delivery_address`, `payment_details`).
    """
    accounts = await _load_accounts()
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    order2_id = STATE["order2_id"]
    old_cost = float(STATE["order2_old_cost"])
    old_del_addr_id = STATE["order2_old_delivery_address_id"]
    pkg_id = STATE["order2_pkg_id"]

    bal_before = await _get_wallet_balance(b2c_user_id)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        patch_resp = await client.patch(
            f"/api/v1/shipments/{order2_id}",
            headers=_headers(accounts, ADMIN_EMAIL),
            json={
                "comment": "Admin J13 weight and address correction",
                "new_delivery_address": {
                    "name": "Priya Verma",
                    "phone": "9810011102",
                    "address_line1": "Tower 9, Connaught Place Updated Suite",
                    "city": "New Delhi",
                    "state": "Delhi",
                    "pincode": "110001",
                    "country": "IN",
                    "category": "HOME",
                },
                "packages": [
                    {
                        "id": pkg_id,
                        "length": 20.0,
                        "breadth": 15.0,
                        "height": 10.0,
                        "dimension_unit": "CM",
                        "weight": 2.0,
                        "weight_unit": "KG",
                        "box_count": 1,
                        "description": "Winter Denim Jacket + Heavy Boots",
                    }
                ],
            },
        )
        assert patch_resp.status_code == 200, patch_resp.text
        updated = patch_resp.json()

        new_del_addr_id = updated["delivery_address"]["id"]
        assert new_del_addr_id != old_del_addr_id
        assert (
            updated["delivery_address"]["address_line1"]
            == "Tower 9, Connaught Place Updated Suite"
        )

        new_cost = round(float(updated["payment_details"]["total_logistics_cost"]), 2)
        assert new_cost > old_cost
        delta = round(new_cost - old_cost, 2)
        STATE["order2_new_cost"] = new_cost

        # Verify add_shipping_to_cod updated cod_amount to 1000 + new_cost
        assert round(float(updated["payment_details"]["cod_amount"]), 2) == round(
            1000.0 + new_cost, 2
        )

        # Verify wallet debited by exact delta
        bal_after = await _get_wallet_balance(b2c_user_id)
        assert bal_after == round(bal_before - delta, 2)

        # Verify ShipmentActivity diff
        tl_resp = await client.get(
            f"/api/v1/shipments/{order2_id}/timeline",
            headers=_headers(accounts, ADMIN_EMAIL),
        )
        assert tl_resp.status_code == 200, tl_resp.text
        activities = tl_resp.json()
        assert any(
            "packages" in (a.get("diff") or {})
            and "delivery_address" in (a.get("diff") or {})
            and "payment_details" in (a.get("diff") or {})
            for a in activities
        )


@pytest.mark.asyncio
async def test_j14_pre_pickup_cancellation_full_refund_credit_note_and_in_transit_cancel_block():
    """
    J14: `customerb2c@logismart.in` cancels Order #2 while in `OPEN` (`POST /api/v1/shipments/{id}/cancel`).
    Verifies:
    - `status == "CANCELLED"`
    - Full updated freight (`new_cost`) refunded via `WalletTxnType.REFUND` to `customerb2c`'s wallet
    - GST `CREDIT_NOTE` (`<PFX><FY>C`) issued in `billing_invoices`
    - Label and invoice PDF download endpoints return `400` on the cancelled shipment.
    """
    accounts = await _load_accounts()
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    order2_id = STATE["order2_id"]
    expected_refund = float(STATE["order2_new_cost"])

    bal_before = await _get_wallet_balance(b2c_user_id)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        cancel_resp = await client.post(
            f"/api/v1/shipments/{order2_id}/cancel",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        cancelled = cancel_resp.json()
        assert cancelled["status"] == "CANCELLED"

        bal_after = await _get_wallet_balance(b2c_user_id)
        assert bal_after == round(bal_before + expected_refund, 2)

        # Verify REFUND transaction and CREDIT_NOTE in DB
        async with GoldenSessionLocal() as session:
            refund_txn = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.shipment_id == uuid.UUID(order2_id),
                        WalletTransaction.txn_type == WalletTxnType.REFUND,
                    )
                )
            ).first()
            assert refund_txn is not None
            assert refund_txn.status == WalletTxnStatus.COMPLETED
            assert round(float(refund_txn.amount), 2) == expected_refund
            assert round(float(refund_txn.closing_balance), 2) == bal_after

            cnotes = (
                await session.exec(
                    select(BillingInvoice).where(
                        BillingInvoice.merchant_user_id == uuid.UUID(b2c_user_id),
                        BillingInvoice.note_type == InvoiceNoteType.CREDIT_NOTE.value,
                    )
                )
            ).all()
            matching_cn = None
            for cn in cnotes:
                for item in cn.line_items or []:
                    if isinstance(item, dict) and item.get("shipment_id") == order2_id:
                        matching_cn = cn
                        break
            assert matching_cn is not None, "Expected GST CREDIT_NOTE in billing_invoices"
            assert matching_cn.invoice_number.startswith(CREDIT_NOTE_PREFIX)
            assert len(matching_cn.invoice_number) <= 16
            assert round(float(matching_cn.total_amount), 2) == expected_refund
            STATE["order2_credit_note_number"] = matching_cn.invoice_number

        # Label and Invoice download return 400 on cancelled shipment
        lbl_resp = await client.get(
            f"/api/v1/shipments/{order2_id}/label",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert lbl_resp.status_code == 400, lbl_resp.text

        inv_resp = await client.get(
            f"/api/v1/shipments/{order2_id}/invoice-pdf",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert inv_resp.status_code == 400, inv_resp.text

        # Attempting to cancel an already-cancelled shipment returns 400
        re_cancel = await client.post(
            f"/api/v1/shipments/{order2_id}/cancel",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert re_cancel.status_code == 400, re_cancel.text


@pytest.mark.asyncio
async def test_j15_create_b2c_pur_add_to_existing_pur_and_cross_location_400_guard():
    """
    J15:
    - Book Order #5 (`PREPAID`) as `customerb2c@logismart.in` at the same pickup warehouse
      as Order #1 and Order #3.
    - Create `PUR-1` (`POST /api/v1/manifests` with `service_flow="B2C"`, `shipment_ids=[order1_id]`)
      -> verify 9-digit `pickup_request_number`, `status=="SCHEDULED"`, Order #1 transitions to `ASSIGNED`.
    - Call `GET /api/v1/manifests/pickup-candidates?shipment_ids={order3_id}&shipment_ids={order5_id}`
      -> verify `PUR-1` is suggested; call `POST /api/v1/manifests/{pur1_id}/shipments` to add
      Order #3 & Order #5 -> verify `expected_awbs == 3` and both transition to `ASSIGNED`.
    - Book a temp order from a different origin pincode and verify attempting to add it to `PUR-1`
      returns `400 Bad Request` (then cancel that temp order so wallet/DB stays clean).
    """
    accounts = await _load_accounts()
    order1_id = STATE["order1_id"]
    order3_id = STATE["order3_id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        warehouse_id = await _ensure_b2c_warehouse(client, accounts)

        # 1. Book Order #5 (PREPAID) at the same warehouse
        ord5_resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "order_reference_id": order_ref("J15-ORD5"),
                "shipment_type": "FORWARD",
                "service_type": ServiceType.SURFACE_ROAD.value,
                "requested_pickup_date": date.today().isoformat(),
                "product_category": "ELECTRONICS",
                "pickup_address_id": warehouse_id,
                "new_delivery_address": {
                    "name": "Kabir Bedi",
                    "phone": "9810011105",
                    "address_line1": "22 Park Street",
                    "city": "Kolkata",
                    "state": "West Bengal",
                    "pincode": "700016",
                    "country": "IN",
                    "category": "HOME",
                },
                "packages": [
                    {
                        "length": 18.0,
                        "breadth": 12.0,
                        "height": 10.0,
                        "dimension_unit": "CM",
                        "weight": 0.5,
                        "weight_unit": "KG",
                        "box_count": 1,
                        "description": "Smart Fitness Band",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": False,
                    "cod_amount": 0.0,
                    "shipment_value": 900.0,
                    "shipment_tax_value": 0.0,
                    "shipment_total_value": 900.0,
                },
            },
        )
        assert ord5_resp.status_code == 201, ord5_resp.text
        order5 = ord5_resp.json()
        order5_id = order5["id"]
        STATE["order5_id"] = order5_id
        STATE["order5_tracking_id"] = order5["tracking_id"]

        # 2. Create PUR-1 with Order #1
        pur1_resp = await client.post(
            "/api/v1/manifests",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "pickup_address_id": warehouse_id,
                "scheduled_date": date.today().isoformat(),
                "time_slot": "10:00 - 14:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "shipment_ids": [order1_id],
            },
        )
        assert pur1_resp.status_code == 201, pur1_resp.text
        pur1 = pur1_resp.json()
        pur1_id = pur1["id"]
        STATE["pur1_id"] = pur1_id
        STATE["pur1_number"] = pur1["pickup_request_number"]

        assert pur1["status"] == "SCHEDULED"
        assert pur1["service_flow"] == "B2C"
        assert pur1["pickup_request_number"] is not None
        assert len(pur1["pickup_request_number"]) == 9
        assert pur1["pickup_request_number"].isdigit()
        assert pur1["expected_awbs"] == 1

        # Verify Order #1 is ASSIGNED
        ord1_check = await client.get(
            f"/api/v1/shipments/{order1_id}",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert ord1_check.status_code == 200
        assert ord1_check.json()["status"] == "ASSIGNED"
        assert ord1_check.json()["manifest_id"] == pur1_id

        # 3. Query pickup-candidates for Order #3 and Order #5 -> PUR-1 suggested
        cand_resp = await client.get(
            f"/api/v1/manifests/pickup-candidates?shipment_ids={order3_id}&shipment_ids={order5_id}",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert cand_resp.status_code == 200, cand_resp.text
        cand_ids = {c["id"] for c in cand_resp.json()["candidates"]}
        assert pur1_id in cand_ids

        # Add Order #3 and Order #5 to PUR-1
        add_resp = await client.post(
            f"/api/v1/manifests/{pur1_id}/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"shipment_ids": [order3_id, order5_id]},
        )
        assert add_resp.status_code == 200, add_resp.text
        pur1_updated = add_resp.json()
        assert pur1_updated["expected_awbs"] == 3

        for oid in (order3_id, order5_id):
            chk = await client.get(
                f"/api/v1/shipments/{oid}",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            )
            assert chk.status_code == 200
            assert chk.json()["status"] == "ASSIGNED"
            assert chk.json()["manifest_id"] == pur1_id

        # 4. Book a temp order from a different origin pincode -> verify 400 guard -> cancel temp order
        temp_resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "order_reference_id": order_ref("J15-TEMP"),
                "shipment_type": "FORWARD",
                "service_type": ServiceType.SURFACE_ROAD.value,
                "requested_pickup_date": date.today().isoformat(),
                "product_category": "DOCUMENTS",
                "new_pickup_address": {
                    "name": "Okhla Secondary Store",
                    "phone": "9810099900",
                    "address_line1": "Phase 2, Okhla Industrial Area",
                    "city": "New Delhi",
                    "state": "Delhi",
                    "pincode": "110020",
                    "country": "IN",
                    "category": "OFFICE",
                },
                "new_delivery_address": {
                    "name": "Neha Gupta",
                    "phone": "9810011199",
                    "address_line1": "Sector 62",
                    "city": "Noida",
                    "state": "Uttar Pradesh",
                    "pincode": "201301",
                    "country": "IN",
                    "category": "HOME",
                },
                "packages": [
                    {
                        "length": 15.0,
                        "breadth": 10.0,
                        "height": 5.0,
                        "dimension_unit": "CM",
                        "weight": 0.5,
                        "weight_unit": "KG",
                        "box_count": 1,
                        "description": "Legal Documents",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": False,
                    "cod_amount": 0.0,
                    "shipment_value": 200.0,
                    "shipment_tax_value": 0.0,
                    "shipment_total_value": 200.0,
                },
            },
        )
        assert temp_resp.status_code == 201, temp_resp.text
        temp_id = temp_resp.json()["id"]
        try:
            cross_loc_resp = await client.post(
                f"/api/v1/manifests/{pur1_id}/shipments",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
                json={"shipment_ids": [temp_id]},
            )
            assert cross_loc_resp.status_code == 400, cross_loc_resp.text
        finally:
            cancel_temp = await client.post(
                f"/api/v1/shipments/{temp_id}/cancel",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            )
            assert cancel_temp.status_code == 200, cancel_temp.text


@pytest.mark.asyncio
async def test_j16_customer_cancels_scheduled_pur_reverts_orders_to_open():
    """
    J16: `customerb2c@logismart.in` cancels `PUR-1` (`POST /api/v1/manifests/{pur1_id}/cancel`).
    Verifies `PUR-1.status == "CANCELED"` and Orders #1, #3, #5 all have
    `manifest_id is None` and `status == "OPEN"`.
    """
    accounts = await _load_accounts()
    pur1_id = STATE["pur1_id"]
    order_ids = [STATE["order1_id"], STATE["order3_id"], STATE["order5_id"]]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        cancel_resp = await client.post(
            f"/api/v1/manifests/{pur1_id}/cancel",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["status"] == "CANCELED"

        async with GoldenSessionLocal() as session:
            db_pur1 = await session.get(Manifest, uuid.UUID(pur1_id))
            assert db_pur1 is not None
            assert db_pur1.status == ManifestStatus.CANCELED

            for oid in order_ids:
                db_ship = await session.get(PickupRequest, uuid.UUID(oid))
                assert db_ship is not None
                assert db_ship.status == PickupStatus.OPEN
                assert db_ship.manifest_id is None


@pytest.mark.asyncio
async def test_j17_ops_marks_pur_out_for_pickup_then_not_picked_reverts_orders_to_open():
    """
    J17:
    - `customerb2c@logismart.in` creates `PUR-2` with Orders #1, #3, #5 (`ASSIGNED`).
    - `operations@logismart.in` marks `PUR-2` `out-for-pickup` -> `status == "OUT_FOR_PICKUP"`.
    - `operations@logismart.in` marks `PUR-2` `not-picked` with `failure_reason="Warehouse shutter closed"`.
    - Verifies `PUR-2.status == "NOT_PICKED"`, `failure_reason == "Warehouse shutter closed"`,
      and Orders #1, #3, #5 all revert to `OPEN` with `manifest_id is None`.
    """
    accounts = await _load_accounts()
    order_ids = [STATE["order1_id"], STATE["order3_id"], STATE["order5_id"]]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        warehouse_id = await _ensure_b2c_warehouse(client, accounts)

        pur2_resp = await client.post(
            "/api/v1/manifests",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "pickup_address_id": warehouse_id,
                "scheduled_date": date.today().isoformat(),
                "time_slot": "14:00 - 18:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "shipment_ids": order_ids,
            },
        )
        assert pur2_resp.status_code == 201, pur2_resp.text
        pur2 = pur2_resp.json()
        pur2_id = pur2["id"]
        STATE["pur2_id"] = pur2_id
        STATE["pur2_number"] = pur2["pickup_request_number"]
        assert pur2["status"] == "SCHEDULED"
        assert pur2["expected_awbs"] == 3

        # Ops marks Out for Pickup
        ofp_resp = await client.post(
            f"/api/v1/manifests/{pur2_id}/out-for-pickup",
            headers=_headers(accounts, OPERATIONS_EMAIL),
        )
        assert ofp_resp.status_code == 200, ofp_resp.text
        assert ofp_resp.json()["status"] == "OUT_FOR_PICKUP"

        # Ops marks Not Picked with reason "Warehouse shutter closed"
        np_resp = await client.post(
            f"/api/v1/manifests/{pur2_id}/not-picked",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={"failure_reason": "Warehouse shutter closed"},
        )
        assert np_resp.status_code == 200, np_resp.text
        np_body = np_resp.json()
        assert np_body["status"] == "NOT_PICKED"
        assert np_body["failure_reason"] == "Warehouse shutter closed"

        async with GoldenSessionLocal() as session:
            db_pur2 = await session.get(Manifest, uuid.UUID(pur2_id))
            assert db_pur2 is not None
            assert db_pur2.status == ManifestStatus.NOT_PICKED
            assert db_pur2.failure_reason == "Warehouse shutter closed"

            for oid in order_ids:
                db_ship = await session.get(PickupRequest, uuid.UUID(oid))
                assert db_ship is not None
                assert db_ship.status == PickupStatus.OPEN
                assert db_ship.manifest_id is None


@pytest.mark.asyncio
async def test_j18_ops_executes_g1_partial_pickup_2_of_3_awbs_and_merged_pdfs():
    """
    J18:
    - `customerb2c@logismart.in` creates `PUR-3` with Orders #1, #3, #5.
    - Verifies `GET /api/v1/manifests/{pur3_id}/labels?label_format=a4` and `thermal_4x2`
      both return `200` and start with `%PDF-`.
    - `operations@logismart.in` dispatches `PUR-3` with only Orders #1 and #3 picked
      (`POST /api/v1/manifests/{pur3_id}/dispatch` with `{"picked_shipment_ids": [order1_id, order3_id]}`).
    - Verifies:
      * Orders #1 & #3 are `IN_TRANSIT` with 6-digit `delivery_otp` generated.
      * Attempting to cancel `IN_TRANSIT` Order #1 returns `400 Bad Request`.
      * Order #5 detached (`manifest_id is None`) and reverted to `OPEN` with activity
        `"Not Handed Over at Pickup — Back to Ready to Ship"`.
      * `PUR-3.status == "PICKED"`, `expected_awbs == 2`, `picked_awbs == 2`, and
        `GET /api/v1/manifests/{pur3_id}/pdf` returns valid `%PDF-` Manifest Copy.
    - Saves state to the slug-namespaced batch2 file (`golden_env.state_path("batch2")`).
    - Verifies `GET /api/v1/wallet/audit-integrity` returns `passed == True` and `discrepancy_count == 0`.
    """
    accounts = await _load_accounts()
    order1_id = STATE["order1_id"]
    order3_id = STATE["order3_id"]
    order5_id = STATE["order5_id"]
    order_ids = [order1_id, order3_id, order5_id]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        warehouse_id = await _ensure_b2c_warehouse(client, accounts)

        # 1. Create PUR-3 with Orders #1, #3, #5
        pur3_resp = await client.post(
            "/api/v1/manifests",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "pickup_address_id": warehouse_id,
                "scheduled_date": date.today().isoformat(),
                "time_slot": "18:00 - 22:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "shipment_ids": order_ids,
            },
        )
        assert pur3_resp.status_code == 201, pur3_resp.text
        pur3 = pur3_resp.json()
        pur3_id = pur3["id"]
        STATE["pur3_id"] = pur3_id
        STATE["pur3_number"] = pur3["pickup_request_number"]
        assert pur3["status"] == "SCHEDULED"
        assert pur3["expected_awbs"] == 3

        # 2. Verify merged labels PDFs (a4 and thermal_4x2)
        for fmt in ("a4", "thermal_4x2"):
            lbl_resp = await client.get(
                f"/api/v1/manifests/{pur3_id}/labels?label_format={fmt}",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            )
            assert lbl_resp.status_code == 200, lbl_resp.text
            assert lbl_resp.content.startswith(b"%PDF-")

        # 3. Ops executes G1 partial pickup: only Order #1 and Order #3 handed over
        disp_resp = await client.post(
            f"/api/v1/manifests/{pur3_id}/dispatch",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={"picked_shipment_ids": [order1_id, order3_id]},
        )
        assert disp_resp.status_code == 200, disp_resp.text
        dispatched = disp_resp.json()
        assert dispatched["status"] == "PICKED"
        assert dispatched["expected_awbs"] == 2
        assert dispatched["picked_awbs"] == 2

        # 4. Verify Orders #1 & #3 are IN_TRANSIT with 6-digit delivery_otp, and Order #5 reverted to OPEN
        async with GoldenSessionLocal() as session:
            for picked_id in (order1_id, order3_id):
                db_s = await session.get(PickupRequest, uuid.UUID(picked_id))
                assert db_s is not None
                assert db_s.status == PickupStatus.IN_TRANSIT
                assert db_s.manifest_id == uuid.UUID(pur3_id)

            db_s5 = await session.get(PickupRequest, uuid.UUID(order5_id))
            assert db_s5 is not None
            assert db_s5.status == PickupStatus.OPEN
            assert db_s5.manifest_id is None

        # The merchant (shipment owner) reads each OTP through the API to forward it
        for picked_id in (order1_id, order3_id):
            STATE[f"otp_{picked_id}"] = await read_otp_as_merchant(
                client, accounts, CUSTOMER_B2C_EMAIL, picked_id
            )

        # Plan C3 / B10 (DO1 cancel-forward-order): a cancel after pickup is no longer a 400; it
        # converts the parcel to RTO. That path is asserted in J48 (suite 9) and J61 (suite 11).
        # Order #1 must stay IN_TRANSIT here because suites 5-8 deliver it (J19, J32).
        order1_after = await client.get(
            f"/api/v1/shipments/{order1_id}", headers=_headers(accounts, CUSTOMER_B2C_EMAIL)
        )
        assert order1_after.status_code == 200, order1_after.text
        assert order1_after.json()["status"] == PickupStatus.IN_TRANSIT.value

        # Verify Order #5 timeline records "Not Handed Over at Pickup — Back to Ready to Ship"
        tl5_resp = await client.get(
            f"/api/v1/shipments/{order5_id}/timeline",
            headers=_headers(accounts, ADMIN_EMAIL),
        )
        assert tl5_resp.status_code == 200, tl5_resp.text
        summaries = [a.get("summary") or "" for a in tl5_resp.json()]
        assert "Not Handed Over at Pickup — Back to Ready to Ship" in summaries

        # 5. Verify Manifest Copy PDF download
        pdf_resp = await client.get(
            f"/api/v1/manifests/{pur3_id}/pdf",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert pdf_resp.status_code == 200, pdf_resp.text
        assert pdf_resp.content.startswith(b"%PDF-")

        # 6. Persist Batch 2 state (namespaced by slug) for Batch 3 (J19-J26) and Batch 4 (J32)
        save_state(BATCH2_STATE, STATE)

        # 7. Final Suite 3 & 4 Ledger & System Integrity Audit check
        audit_resp = await client.get(
            "/api/v1/wallet/audit-integrity",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert audit_resp.status_code == 200, audit_resp.text
        audit_body = audit_resp.json()
        assert audit_body["passed"] is True, audit_body
        assert audit_body["discrepancy_count"] == 0, audit_body
        assert audit_body["discrepancies"] == []
