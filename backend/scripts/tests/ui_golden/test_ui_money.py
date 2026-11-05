"""
UI money journey (ship-readiness plan E3): one B2C parcel from booking to COD payout,
plus one B2B LR booking, clicked through the money screens with screen ₹ == DB ₹ at
every step (Zero Frontend Math: the screen may only show what the backend computed).

Screens: B2C booking + quote, admin edit with server re-price preview, mobile `/ops`
pickup with actual pieces, hub measurement, delivery with OTP, wallet, weight
mismatch + claim, invoices, COD remittances, B2B booking + quote.

Non-money glue (pickup request, OTP lookup, remittance batch) goes through the REST
API (`api_setup`); every assertion reads the database through the read-only
`DbOracle`.
"""

from decimal import Decimal

import httpx
import pytest

pytest.importorskip("playwright.async_api")

from golden_journeys.golden_env import (  # noqa: E402
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    OPERATIONS_EMAIL,
    get_wallet_balance,
    headers,
    load_accounts,
    make_utr,
)

from app.models.delhivery_modules import (  # noqa: E402
    InvoiceNoteType,
    WeightDisputeClaimStatus,
)
from app.models.pickups import PickupStatus, ServiceOption  # noqa: E402

from .api_setup import (  # noqa: E402
    API_TIMEOUT_S,
    create_b2c_cod_remittance,
    create_b2c_pickup_request,
    delivery_otp,
)
from .db_oracle import DbOracle  # noqa: E402
from .money import to_paisa  # noqa: E402
from .pages.booking_page import (  # noqa: E402
    B2BBookingPage,
    B2CBookingPage,
    BookingInput,
    PackageInput,
)
from .pages.finance_pages import InvoicesPage, RemittancesPage, WalletPage  # noqa: E402
from .pages.ops_page import OpsMobilePage  # noqa: E402
from .pages.shipment_pages import ShipmentDetailPage, ShipmentEditPage  # noqa: E402
from .pages.weight_mismatch_page import WeightMismatchPage  # noqa: E402
from .ui_config import DESKTOP, PHONE  # noqa: E402
from .ui_fixtures import TabFactory, UiSettings, api_url  # noqa: E402

JOURNEY = "MONEY"
WALLET_TOPUP_INR = 20_000.0
B2C_PICKUP_LABEL = "LogiSmart B2C Gurugram Hub Warehouse"
"""Seeded private warehouse of customerb2c (`fixtures/logismart_test_addresses.json`)."""
B2B_PICKUP_LABEL = "B2B Dock Manager"
"""Seeded private pickup address of customerb2b (same fixture)."""
B2C_GOODS_VALUE = "5000"
B2C_BOX_CM = ("10", "10", "10")
B2C_BOOKED_WEIGHT_KG = "1"
B2C_EDITED_WEIGHT_KG = "2"
B2C_MEASURED_WEIGHT_KG = "5"
B2C_ACTUAL_PIECES = "1"
CLAIMED_WEIGHT_G = "2000"
DELIVERED_LABEL = "Delivered"
RECEIVED_BY = "Jane Doe"


def _b2c_booking() -> BookingInput:
    """COD B2C parcel Gurugram -> New Delhi on Delhivery Express, 1 box of 1 kg."""
    return BookingInput(
        pickup_address_label=B2C_PICKUP_LABEL,
        delivery_name=RECEIVED_BY,
        delivery_phone="9876543210",
        delivery_line1="123 Delivery St",
        delivery_pincode="110001",
        delivery_city="New Delhi",
        delivery_state="DL",
        category_label="Electronics & Gadgets",
        payment_mode_label="Prepaid",
        goods_value=B2C_GOODS_VALUE,
        service_option=ServiceOption.DELHIVERY_EXPRESS.value,
        packages=[PackageInput(*B2C_BOX_CM, B2C_BOOKED_WEIGHT_KG, "1")],
        is_cod=True,
    )


def _b2b_booking() -> BookingInput:
    """Prepaid B2B LR Gurugram -> Mumbai on Logismart Prime with PO, e-way bill and carrier's risk."""
    return BookingInput(
        pickup_address_label=B2B_PICKUP_LABEL,
        delivery_name="Acme Corp",
        delivery_phone="9876543211",
        delivery_line1="456 B2B Ave",
        delivery_pincode="400001",
        delivery_city="Mumbai",
        delivery_state="MH",
        category_label="Apparel & Clothing",
        payment_mode_label="Prepaid",
        goods_value="10000",
        service_option=ServiceOption.PRIME_SURFACE.value,
        packages=[PackageInput("20", "20", "20", "5", "2")],
        po_number="PO-123",
        eway_bill="123456789012",
        carriers_risk=True,
    )


async def _ensure_b2c_wallet_funded() -> None:
    """
    Tops up `customerb2c` via the UPI recharge + admin approval API when its balance is
    below `WALLET_TOPUP_INR / 2`, so standalone runs satisfy the positive-wallet COD
    remittance guard without depending on `test_suite_10_crosscut` running first.
    """
    accounts = await load_accounts()
    if await get_wallet_balance(accounts[CUSTOMER_B2C_EMAIL]["id"]) >= WALLET_TOPUP_INR / 2:
        return
    cust_headers = headers(accounts, CUSTOMER_B2C_EMAIL)
    admin_headers = headers(accounts, ADMIN_EMAIL)
    async with httpx.AsyncClient(base_url=api_url(), timeout=API_TIMEOUT_S) as client:
        intent = await client.post(
            "/api/v1/wallet/recharge/upi-intent",
            headers=cust_headers,
            json={"amount": WALLET_TOPUP_INR},
        )
        assert intent.status_code == 200, intent.text
        txn_id = intent.json()["transaction_id"]
        confirm = await client.post(
            f"/api/v1/wallet/recharge/{txn_id}/confirm",
            headers=cust_headers,
            json={"utr_number": make_utr()},
        )
        assert confirm.status_code == 200, confirm.text
        approve = await client.post(
            f"/api/v1/wallet/recharge/{txn_id}/approve",
            headers=admin_headers,
        )
        assert approve.status_code == 200, approve.text


@pytest.mark.ui
async def test_ui_money_flows(
    role_tabs: TabFactory, ui_settings: UiSettings, step_banner, db_oracle: DbOracle
) -> None:
    """Books, edits, picks up, measures, delivers and remits one parcel through the UI."""
    b2c_tab = await role_tabs.as_role(CUSTOMER_B2C_EMAIL, DESKTOP)
    admin_tab = await role_tabs.as_role(ADMIN_EMAIL, DESKTOP)
    ops_tab = await role_tabs.as_role(OPERATIONS_EMAIL, PHONE)
    merchant_id = await db_oracle.user_id(CUSTOMER_B2C_EMAIL)

    # 1. B2C booking: the quoted total is what gets stored.
    booked = await B2CBookingPage(b2c_tab.page, ui_settings, step_banner).book(_b2c_booking())
    stored = await db_oracle.shipment(booked.awb)
    assert booked.quoted_total == stored.total_logistics_cost
    shipment_id = str(stored.shipment_id)

    # 2. Admin edit: the server preview starts from the stored bill and becomes the new bill.
    edit = ShipmentEditPage(admin_tab.page, ui_settings, step_banner)
    await edit.open_edit(shipment_id, is_b2b=False)
    await edit.set_package_weight(0, B2C_EDITED_WEIGHT_KG)
    preview = await edit.read_preview()
    assert preview.old_total == stored.total_logistics_cost
    assert preview.new_total - preview.old_total == preview.delta
    await edit.save()
    edited = await db_oracle.shipment(booked.awb)
    assert edited.total_logistics_cost == preview.new_total

    # 3. Pickup request (API glue), then the rider confirms actual pieces + seller's pickup OTP on the phone.
    pur = await create_b2c_pickup_request(
        CUSTOMER_B2C_EMAIL, str(edited.pickup_address_id), [shipment_id]
    )
    ops = OpsMobilePage(ops_tab.page, ui_settings, step_banner)
    await ops.open()
    await ops.confirm_pickup(
        pur["pickup_request_number"],
        {booked.awb: B2C_ACTUAL_PIECES},
        pickup_otp=pur.get("pickup_otp"),
    )
    picked = await db_oracle.shipment(booked.awb)
    assert picked.status == PickupStatus.IN_TRANSIT.value

    # 4. Hub scale: a heavier measurement re-prices the parcel and opens a weight dispute.
    detail = ShipmentDetailPage(ops_tab.page, ui_settings, step_banner)
    await detail.open_shipment(shipment_id, is_b2b=False)
    dialog = await detail.open_measurement_dialog()
    await dialog.submit(B2C_MEASURED_WEIGHT_KG, *B2C_BOX_CM)
    measured = await db_oracle.shipment(booked.awb)
    assert measured.total_logistics_cost > picked.total_logistics_cost
    dispute = await db_oracle.weight_dispute(booked.awb)
    assert dispute.claim_status == WeightDisputeClaimStatus.NONE.value

    # 5. Delivery with the consignee's OTP (H-11).
    await detail.open_shipment(shipment_id, is_b2b=False)
    await detail.update_status(
        status_label=DELIVERED_LABEL,
        comment="Delivered to consignee",
        delivery_otp=await delivery_otp(CUSTOMER_B2C_EMAIL, shipment_id),
        pod_received_by=RECEIVED_BY,
    )
    delivered = await db_oracle.shipment(booked.awb)
    assert delivered.status == PickupStatus.COMPLETED.value

    # 6. Merchant wallet: the screen shows the stored balance.
    wallet = WalletPage(b2c_tab.page, ui_settings, step_banner)
    await wallet.open()
    screen_balance = await wallet.balance()
    assert screen_balance == await db_oracle.wallet_balance(merchant_id)

    # 7. Weight mismatch: the screen shows the stored extra charge; the merchant claims it.
    weight = WeightMismatchPage(b2c_tab.page, ui_settings, step_banner)
    await weight.open()
    screen_cost_diff = await weight.cost_diff(booked.awb)
    assert screen_cost_diff == to_paisa(dispute.cost_diff_inr)
    await weight.raise_claim(booked.awb, CLAIMED_WEIGHT_G, "Packed weight was 2 kg")
    claimed = await db_oracle.weight_dispute(booked.awb)
    assert claimed.claim_status == WeightDisputeClaimStatus.CLAIM_RAISED.value

    # 8. Invoices: the booking invoice row shows the stored GST total.
    documents = await db_oracle.gst_documents(stored.shipment_id)
    invoice = next(d for d in documents if d.note_type == InvoiceNoteType.INVOICE.value)
    invoices = InvoicesPage(b2c_tab.page, ui_settings, step_banner)
    await invoices.open()
    screen_invoice_total = await invoices.row_total(invoice.invoice_number)
    assert screen_invoice_total == invoice.total_amount

    # 9. COD payout (API glue: ensure merchant wallet >= 0, then finance closes the batch).
    await _ensure_b2c_wallet_funded()
    remittance = await create_b2c_cod_remittance(shipment_id)
    stored_remittance = await db_oracle.remittance(remittance["remittance_number"])
    assert to_paisa(stored_remittance.total_remittance) > Decimal("0.00")
    remittances = RemittancesPage(b2c_tab.page, ui_settings, step_banner)
    await remittances.open()
    screen_remittance_total = await remittances.row_total(remittance["remittance_number"])
    assert screen_remittance_total == to_paisa(stored_remittance.total_remittance)

    # 10. B2B LR booking: the quoted total is what gets stored.
    b2b_tab = await role_tabs.as_role(CUSTOMER_B2B_EMAIL, DESKTOP)
    lr = await B2BBookingPage(b2b_tab.page, ui_settings, step_banner).book(_b2b_booking())
    stored_lr = await db_oracle.shipment(lr.awb)
    assert lr.quoted_total == stored_lr.total_logistics_cost
