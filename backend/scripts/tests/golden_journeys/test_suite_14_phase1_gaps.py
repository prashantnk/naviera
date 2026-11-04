"""
Golden Journeys suite 14: Phase-1 flows that had no DB-backed API journey (qa4, 2026-11-04).

Every flow below is listed as a GAP in `llm_resources/.agents/phase1qa/FLOW_MATRIX.md`:

- J64 (G1) Admin price override `POST /shipments/{id}/admin-charge`: overpriced -> REFUND +
  CREDIT_NOTE, underpriced -> SPEND + DEBIT_NOTE, extra pre-GST charge, idempotent replay,
  staff/customer 403s, and public tracking never shows the money.
- J65 (G2) Admin offline wallet credit `POST /wallet/admin/credit`: RECHARGE row with a
  receipt, balance == ledger, duplicate reference 409, replay, non-admin 403s.
- J66 (G3) Carrier booking/bill `GET/PUT /shipments/{id}/carrier-billing`: staff-only view,
  AWB + charged amount saved, under-recovery gap verdict, duplicate AWB 409, no leak to the
  customer.
- J67 (G4) Weight-mismatch CSV export, scoped per merchant.
- J68 (G5) NDR actions UPLOAD_DOCUMENT, BOOK_APPOINTMENT, CANCEL_PICKUP (refund + CREDIT_NOTE)
  and B2B REPACK_AND_DELIVER executed end to end.
- J69 (G6) Prime lanes export -> real (non-dry-run) import of the same file is a no-op.

Prices come from the deterministic fake Delhivery bound to `logismart-test` by `golden_env`
(same rate card as suite 9). Helpers are shared with suite 9 so both suites agree on the money
oracle. Spring analogy: an extra `@SpringBootTest` class reusing the suite-9 test fixtures.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Mapping

import httpx
import pytest
from sqlmodel import col, select

from app.models.delhivery_modules import InvoiceNoteType
from app.models.pickups import (
    NdrAction,
    NdrExceptionReason,
    PickupDocument,
    PickupStatus,
    ShipmentActivity,
)
from app.models.prime import PrimeLane
from app.models.repricing import ChargeAdjustmentReason
from app.models.wallet import WalletTransaction, WalletTxnType

from .golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GOLDEN_TENANT_SLUG,
    OPERATIONS_EMAIL,
    OWNER_EMAIL,
    READONLY_EMAIL,
    RUN_TAG,
    SUPPORT_EMAIL,
    GoldenSessionLocal,
    get_tenant_id,
    get_wallet_balance,
    headers,
    load_accounts,
)
from .test_suite_9_repricing import (
    B2B_BOX_CM,
    B2B_DROP_PINCODE,
    P_2KG,
    P_B2B_4BOX,
    TIME_SLOT,
    M,
    _action,
    _b2b_dock,
    _b2c_warehouse,
    _book,
    _book_and_dispatch_b2c_2kg,
    _book_b2c_2kg,
    _box,
    _client,
    _dispatch,
    _get,
    _measure,
    _payment,
    _raise_exception,
    _txn_type,
    assert_adjustment,
    assert_gst_note,
    assert_money_invariants,
    assert_wallet_matches_ledger,
    assert_wallet_step,
    new_rows,
    only,
    snapshot,
)

NON_ADMIN_EMAILS = (OPERATIONS_EMAIL, SUPPORT_EMAIL, READONLY_EMAIL, CUSTOMER_B2C_EMAIL)
OVERPRICED_TOTAL = Decimal("100.00")
UNDERPRICED_TOTAL = Decimal("200.00")
EXTRA_PRE_GST = Decimal("50.00")
EXTRA_GROSS = Decimal("59.00")  # Rs.50 + 18 % GST
OFFLINE_CREDIT = Decimal("2500.00")
CARRIER_CHARGE_ABOVE_BILL = Decimal("250.00")
DOCUMENT_URL = "https://example.com/qa/invoice-qa4.pdf"


async def _admin_charge(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    sid: str,
    email: str,
    body: Dict[str, Any],
    key: str,
) -> httpx.Response:
    """POST /shipments/{id}/admin-charge with an explicit Idempotency-Key."""
    hdrs = headers(accounts, email)
    hdrs["Idempotency-Key"] = key
    return await client.post(f"/api/v1/shipments/{sid}/admin-charge", headers=hdrs, json=body)


async def _activities(sid: str) -> list:
    """ShipmentActivity rows of one shipment, oldest first."""
    async with GoldenSessionLocal() as session:
        rows = (
            await session.exec(
                select(ShipmentActivity)
                .where(ShipmentActivity.pickup_id == uuid.UUID(sid))
                .order_by(col(ShipmentActivity.timestamp))
            )
        ).all()
        await session.rollback()
    return list(rows)


# =============================================================================
# J64 (G1): Admin price override
# =============================================================================


@pytest.mark.asyncio
async def test_j64_admin_price_override_both_ways_extra_charge_and_403s():
    """
    2 kg B2C parcel Rs.159.30 (wallet-billed). Ops/support/readonly/customer get 403.
    Admin overrides to Rs.100.00 -> REFUND Rs.59.30 + CREDIT_NOTE; then to Rs.200.00 ->
    SPEND Rs.100.00 + DEBIT_NOTE; then adds Rs.50 pre-GST -> SPEND Rs.59.00 + DEBIT_NOTE.
    A replayed key moves no money. Every step keeps the money invariants and writes one
    ADMIN_EDIT adjustment; public tracking never shows the override.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        parcel = await _book_b2c_2kg(client, accounts, "J64")
        sid, awb = parcel["id"], parcel["tracking_id"]
        assert M(parcel["payment_details"]["total_logistics_cost"]) == P_2KG

        for email in NON_ADMIN_EMAILS:
            denied = await _admin_charge(
                client, accounts, sid, email,
                {"override_total_price": float(OVERPRICED_TOTAL), "label": "J64 denied"},
                f"j64-deny-{email}-{RUN_TAG}",
            )
            assert denied.status_code == 403, (email, denied.text)
        empty = await _admin_charge(client, accounts, sid, ADMIN_EMAIL, {"label": "J64 empty"}, f"j64-empty-{RUN_TAG}")
        assert empty.status_code == 400, empty.text

        steps = (
            ({"override_total_price": float(OVERPRICED_TOTAL), "label": "J64 overpriced"},
             OVERPRICED_TOTAL, WalletTxnType.REFUND, InvoiceNoteType.CREDIT_NOTE, P_2KG - OVERPRICED_TOTAL),
            ({"override_total_price": float(UNDERPRICED_TOTAL), "label": "J64 underpriced"},
             UNDERPRICED_TOTAL, WalletTxnType.SPEND, InvoiceNoteType.DEBIT_NOTE, UNDERPRICED_TOTAL - OVERPRICED_TOTAL),
            ({"amount": float(EXTRA_PRE_GST), "includes_gst": False, "label": "J64 extra handling"},
             UNDERPRICED_TOTAL + EXTRA_GROSS, WalletTxnType.SPEND, InvoiceNoteType.DEBIT_NOTE, EXTRA_GROSS),
        )
        old_total = P_2KG
        for index, (body, new_total, txn_type, note_type, amount) in enumerate(steps):
            before = await snapshot(sid)
            bal = await get_wallet_balance(merchant_id)
            key = f"j64-step{index}-{RUN_TAG}"
            resp = await _admin_charge(client, accounts, sid, ADMIN_EMAIL, body, key)
            assert resp.status_code == 200, resp.text
            assert M(resp.json()["seller_billed_amount"]) == new_total
            wallet_delta = amount if txn_type == WalletTxnType.REFUND else -amount
            await assert_wallet_step(merchant_id, bal, wallet_delta)
            after = await assert_money_invariants(sid)
            assert after.total == new_total
            step = new_rows(before, after)
            assert _txn_type(only(step.txns, f"step {index} txn")) == txn_type.value
            assert_gst_note(only(step.notes, f"step {index} note"), note_type=note_type, amount=amount, shipment_id=sid)
            assert_adjustment(
                only(step.adjustments, f"step {index} adjustment"),
                reasons={ChargeAdjustmentReason.ADMIN_EDIT}, old=old_total, new=new_total,
            )
            replay = await _admin_charge(client, accounts, sid, ADMIN_EMAIL, body, key)
            assert replay.status_code == 200, replay.text
            replayed = new_rows(after, await snapshot(sid))
            assert (replayed.txns, replayed.notes, replayed.adjustments) == ([], [], [])
            old_total = new_total

        overrides = [a for a in await _activities(sid) if (a.summary or "").startswith("Admin Price Override")]
        assert len(overrides) == len(steps)

        public = await client.get(f"/api/v1/tracking/{awb}", headers={"X-Tenant-Slug": GOLDEN_TENANT_SLUG})
        assert public.status_code == 200, public.text
        assert "Admin Price Override" not in public.text and "₹" not in public.text


# =============================================================================
# J65 (G2): Admin offline wallet credit
# =============================================================================


@pytest.mark.asyncio
async def test_j65_admin_offline_credit_receipt_ledger_duplicate_and_403s():
    """
    Owner/admin record an offline NEFT credit for customerb2c: one COMPLETED RECHARGE row
    with a REC- receipt and the exact opening/closing balance, wallet == ledger. The same
    reference again is 409; the same Idempotency-Key replays without a second row; every
    other role gets 403 and an unknown email is refused.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    reference = f"NEFTQA{uuid.uuid4().hex[:12].upper()}"
    body = {
        "user_email": CUSTOMER_B2C_EMAIL,
        "amount": float(OFFLINE_CREDIT),
        "utr_number": reference,
        "payment_method": "NEFT / IMPS / RTGS",
        "notes": "J65 offline credit",
    }
    async with _client() as client:
        for email in NON_ADMIN_EMAILS:
            hdrs = headers(accounts, email)
            hdrs["Idempotency-Key"] = f"j65-deny-{email}-{RUN_TAG}"
            denied = await client.post("/api/v1/wallet/admin/credit", headers=hdrs, json=body)
            assert denied.status_code == 403, (email, denied.text)

        bal = await get_wallet_balance(merchant_id)
        hdrs = headers(accounts, ADMIN_EMAIL)
        hdrs["Idempotency-Key"] = f"j65-credit-{RUN_TAG}"
        resp = await client.post("/api/v1/wallet/admin/credit", headers=hdrs, json=body)
        assert resp.status_code == 200, resp.text
        txn = resp.json()["transaction"]
        assert txn["txn_type"] == WalletTxnType.RECHARGE.value
        assert txn["status"] == "COMPLETED"
        assert (txn["receipt_number"] or "").startswith("REC-")
        assert M(txn["amount"]) == OFFLINE_CREDIT
        assert M(txn["closing_balance"]) == M(txn["opening_balance"]) + OFFLINE_CREDIT
        await assert_wallet_step(merchant_id, bal, OFFLINE_CREDIT)
        await assert_wallet_matches_ledger(merchant_id)

        replay = await client.post("/api/v1/wallet/admin/credit", headers=hdrs, json=body)
        assert replay.status_code == 200, replay.text
        assert replay.json()["transaction"]["id"] == txn["id"]

        dup_hdrs = headers(accounts, OWNER_EMAIL)
        dup_hdrs["Idempotency-Key"] = f"j65-dup-{RUN_TAG}"
        duplicate = await client.post("/api/v1/wallet/admin/credit", headers=dup_hdrs, json=body)
        assert duplicate.status_code == 409, duplicate.text

        unknown_hdrs = headers(accounts, ADMIN_EMAIL)
        unknown_hdrs["Idempotency-Key"] = f"j65-unknown-{RUN_TAG}"
        unknown = await client.post(
            "/api/v1/wallet/admin/credit",
            headers=unknown_hdrs,
            json={**body, "user_email": f"nobody-{RUN_TAG}@logismart.in", "utr_number": f"{reference}X"},
        )
        assert unknown.status_code in (400, 404), unknown.text
        await assert_wallet_step(merchant_id, bal, OFFLINE_CREDIT)

        tenant_id = await get_tenant_id()
        async with GoldenSessionLocal() as session:
            rows = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.tenant_id == tenant_id,
                        WalletTransaction.utr_number == reference,
                    )
                )
            ).all()
            await session.rollback()
        assert len(rows) == 1, "exactly one ledger row for the offline reference"


# =============================================================================
# J66 (G3): Carrier booking / bill
# =============================================================================


@pytest.mark.asyncio
async def test_j66_carrier_billing_staff_only_gap_verdict_and_duplicate_awb():
    """
    Ops copy the Delhivery AWB and the carrier's charge from one.delhivery.com. Customers get
    403 on GET and PUT, support/readonly 403 on PUT. A charge above the seller's pre-GST bill
    flags an under-recovery gap. The same carrier AWB on a second shipment is 409. The
    customer's shipment JSON never carries carrier cost or margin.
    """
    accounts = await load_accounts()
    carrier_awb = f"QA4{uuid.uuid4().hex[:10].upper()}"
    async with _client() as client:
        first = await _book_b2c_2kg(client, accounts, "J66A")
        second = await _book_b2c_2kg(client, accounts, "J66B")
        sid = first["id"]
        url = f"/api/v1/shipments/{sid}/carrier-billing"

        cust_get = await client.get(url, headers=headers(accounts, CUSTOMER_B2C_EMAIL))
        assert cust_get.status_code == 403, cust_get.text
        empty = await client.get(url, headers=headers(accounts, OPERATIONS_EMAIL))
        assert empty.status_code == 200, empty.text
        assert empty.json()["carrier_awb"] is None and empty.json()["has_gap"] is False

        body = {"carrier_awb": f"  {carrier_awb} ", "charged_amount": float(CARRIER_CHARGE_ABOVE_BILL)}
        for email in (CUSTOMER_B2C_EMAIL, SUPPORT_EMAIL, READONLY_EMAIL):
            denied = await client.put(url, headers=headers(accounts, email), json=body)
            assert denied.status_code == 403, (email, denied.text)

        before = await snapshot(sid)
        saved = await client.put(url, headers=headers(accounts, OPERATIONS_EMAIL), json=body)
        assert saved.status_code == 200, saved.text
        view = saved.json()
        assert view["carrier_awb"] == carrier_awb
        assert M(view["charged_amount"]) == CARRIER_CHARGE_ABOVE_BILL
        assert view["has_gap"] is True and M(view["gap_amount"]) > 0
        assert M(view["seller_billed_amount"]) == P_2KG
        after = await assert_money_invariants(sid)
        step = new_rows(before, after)
        assert (step.txns, step.notes, step.adjustments) == ([], [], []), "a carrier bill never re-bills the seller"
        assert after.shipment.carrier_awb == carrier_awb

        reread = await client.get(url, headers=headers(accounts, ADMIN_EMAIL))
        assert reread.status_code == 200 and reread.json()["carrier_awb"] == carrier_awb

        dup = await client.put(
            f"/api/v1/shipments/{second['id']}/carrier-billing",
            headers=headers(accounts, OPERATIONS_EMAIL),
            json={"carrier_awb": carrier_awb},
        )
        assert dup.status_code == 409, dup.text

        customer_view = await client.get(f"/api/v1/shipments/{sid}", headers=headers(accounts, CUSTOMER_B2C_EMAIL))
        assert customer_view.status_code == 200, customer_view.text
        for leaked in ("carrier_cost", "margin_amount", "carrier_charged_taxable", "charged_amount"):
            assert leaked not in customer_view.text, f"customer shipment JSON leaks {leaked}"


# =============================================================================
# J67 (G4): Weight-mismatch CSV export
# =============================================================================


@pytest.mark.asyncio
async def test_j67_weight_mismatch_csv_export_is_scoped_per_merchant():
    """A hub re-weigh creates a Weight Mismatch row; its CSV lists the AWB for the merchant,
    the admin and readonly, and not for another merchant."""
    accounts = await load_accounts()
    async with _client() as client:
        shipment = await _book_and_dispatch_b2c_2kg(client, accounts, "J67")
        sid, awb = shipment["id"], shipment["tracking_id"]
        measured = await _measure(client, accounts, sid, weight_kg=3.5)
        assert measured.status_code == 200, measured.text
        await assert_money_invariants(sid)

        for email, should_see in (
            (CUSTOMER_B2C_EMAIL, True),
            (ADMIN_EMAIL, True),
            (READONLY_EMAIL, True),
            (CUSTOMER_B2B_EMAIL, False),
        ):
            resp = await client.get(
                "/api/v1/disputes/weight-mismatch/export/csv", headers=headers(accounts, email)
            )
            assert resp.status_code == 200, (email, resp.text)
            assert resp.headers["content-type"].startswith("text/csv")
            assert "attachment" in resp.headers.get("content-disposition", "")
            lines = [line for line in resp.text.splitlines() if line.strip()]
            assert lines, f"{email}: CSV has no header row"
            assert (awb in resp.text) is should_see, f"{email}: AWB visibility should be {should_see}"


# =============================================================================
# J68 (G5): NDR actions with no end-to-end coverage
# =============================================================================


@pytest.mark.asyncio
async def test_j68_ndr_upload_document_book_appointment_cancel_pickup_and_b2b_repack():
    """
    A) DOCUMENT_NEEDED -> merchant UPLOAD_DOCUMENT (non-http URL refused) -> back In transit,
       one pickup_documents row.
    B) APPOINTMENT_NEEDED -> BOOK_APPOINTMENT (end before start refused) -> slot saved.
    C) PICKUP_FAILED on a parcel in a Pickup Request (ASSIGNED) -> CANCEL_PICKUP -> CANCELLED, REFUND Rs.159.30 + CREDIT_NOTE.
    D) B2B LR DAMAGED -> REPACK_AND_DELIVER -> back In transit, no money moves.
    Each action writes a ShipmentActivity row.
    """
    accounts = await load_accounts()
    merchant_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    async with _client() as client:
        # A) UPLOAD_DOCUMENT
        doc_parcel = await _book_and_dispatch_b2c_2kg(client, accounts, "J68A")
        doc_id = doc_parcel["id"]
        await _raise_exception(client, accounts, doc_id, NdrExceptionReason.DOCUMENT_NEEDED)
        bad = await client.post(
            f"/api/v1/exceptions/{doc_id}/actions",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"action": NdrAction.UPLOAD_DOCUMENT.value, "document_type": "GST_INVOICE", "document_url": "ftp://x/y.pdf"},
        )
        assert bad.status_code == 400, bad.text
        await _action(
            client, accounts, doc_id, CUSTOMER_B2C_EMAIL,
            {"action": NdrAction.UPLOAD_DOCUMENT.value, "document_type": "GST_INVOICE", "document_url": DOCUMENT_URL},
        )
        assert (await _get(client, accounts, doc_id))["status"] == PickupStatus.IN_TRANSIT.value
        async with GoldenSessionLocal() as session:
            docs = (
                await session.exec(select(PickupDocument).where(PickupDocument.pickup_id == uuid.UUID(doc_id)))
            ).all()
            await session.rollback()
        assert [d.file_url for d in docs] == [DOCUMENT_URL]
        assert any((a.summary or "").startswith("Document uploaded") for a in await _activities(doc_id))

        # B) BOOK_APPOINTMENT
        appt_parcel = await _book_and_dispatch_b2c_2kg(client, accounts, "J68B")
        appt_id = appt_parcel["id"]
        await _raise_exception(client, accounts, appt_id, NdrExceptionReason.APPOINTMENT_NEEDED)
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=5, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=4)
        reversed_window = await client.post(
            f"/api/v1/exceptions/{appt_id}/actions",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"action": NdrAction.BOOK_APPOINTMENT.value, "appointment_start": end.isoformat(), "appointment_end": start.isoformat()},
        )
        assert reversed_window.status_code == 422, reversed_window.text
        await _action(
            client, accounts, appt_id, CUSTOMER_B2C_EMAIL,
            {"action": NdrAction.BOOK_APPOINTMENT.value, "appointment_start": start.isoformat(), "appointment_end": end.isoformat()},
        )
        snap = await snapshot(appt_id)
        assert snap.shipment.status == PickupStatus.IN_TRANSIT
        assert snap.shipment.appointment_start == start and snap.shipment.appointment_end == end
        assert any((a.summary or "").startswith("Delivery appointment booked") for a in await _activities(appt_id))

        # C) CANCEL_PICKUP (pre-pickup) refunds in full with a credit note
        pickup_parcel = await _book_b2c_2kg(client, accounts, "J68C")
        pickup_id = pickup_parcel["id"]
        pur = await client.post(
            "/api/v1/manifests",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "pickup_address_id": await _b2c_warehouse(client, accounts),
                "scheduled_date": date.today().isoformat(),
                "time_slot": TIME_SLOT,
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "shipment_ids": [pickup_id],
            },
        )
        assert pur.status_code == 201, pur.text
        assert (await _get(client, accounts, pickup_id))["status"] == PickupStatus.ASSIGNED.value
        await _raise_exception(client, accounts, pickup_id, NdrExceptionReason.PICKUP_FAILED)
        before = await snapshot(pickup_id)
        bal = await get_wallet_balance(merchant_id)
        await _action(client, accounts, pickup_id, CUSTOMER_B2C_EMAIL, {"action": NdrAction.CANCEL_PICKUP.value})
        after = await assert_money_invariants(pickup_id)
        assert after.shipment.status == PickupStatus.CANCELLED
        await assert_wallet_step(merchant_id, bal, P_2KG)
        step = new_rows(before, after)
        assert _txn_type(only(step.txns, "cancel refund")) == WalletTxnType.REFUND.value
        assert_gst_note(only(step.notes, "cancel CN"), note_type=InvoiceNoteType.CREDIT_NOTE, amount=P_2KG, shipment_id=pickup_id)

        # D) B2B REPACK_AND_DELIVER
        dock_id = await _b2b_dock(client, accounts)
        lr = await _book(
            client, accounts, CUSTOMER_B2B_EMAIL, label="J68D",
            pickup_address_id=dock_id, packages=[_box(B2B_BOX_CM, 25.0, 4)],
            payment=_payment(goods=40000.0), product_category="COMMERCIAL",
            drop_pincode=B2B_DROP_PINCODE,
        )
        lid = lr["id"]
        assert M(lr["payment_details"]["total_logistics_cost"]) == P_B2B_4BOX
        await _dispatch(client, accounts, CUSTOMER_B2B_EMAIL, dock_id, [lid], service_flow="B2B")
        assert (await _get(client, accounts, lid))["status"] == PickupStatus.IN_TRANSIT.value
        await _raise_exception(client, accounts, lid, NdrExceptionReason.DAMAGED)
        before = await snapshot(lid)
        await _action(client, accounts, lid, CUSTOMER_B2B_EMAIL, {"action": NdrAction.REPACK_AND_DELIVER.value})
        after = await assert_money_invariants(lid)
        assert after.shipment.status == PickupStatus.IN_TRANSIT
        step = new_rows(before, after)
        assert (step.txns, step.notes, step.adjustments) == ([], [], [])
        assert any((a.summary or "").startswith("Repack and deliver authorised") for a in await _activities(lid))


# =============================================================================
# J69 (G6): Prime lanes real import
# =============================================================================


@pytest.mark.asyncio
async def test_j69_prime_lanes_export_then_real_import_is_a_no_op():
    """Admin exports the lanes CSV and imports it for real (dry_run=false): nothing is
    created, updated or deactivated and the lane rows are unchanged. Customers get 403."""
    accounts = await load_accounts()
    tenant_id = await get_tenant_id()

    async def _lanes() -> list:
        async with GoldenSessionLocal() as session:
            rows = (await session.exec(select(PrimeLane).where(PrimeLane.tenant_id == tenant_id))).all()
            await session.rollback()
        return sorted((str(r.id), bool(r.is_active)) for r in rows)

    async with _client() as client:
        exported = await client.get("/api/v1/pricing/prime-lanes/export.csv", headers=headers(accounts, ADMIN_EMAIL))
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith("text/csv")
        lanes_before = await _lanes()
        assert lanes_before, "the golden reset seeds the Prime fixture lanes"

        cust_hdrs = {**headers(accounts, CUSTOMER_B2B_EMAIL), "Content-Type": "text/csv"}
        denied = await client.post(
            "/api/v1/pricing/prime-lanes/import?dry_run=false", headers=cust_hdrs, content=exported.content
        )
        assert denied.status_code == 403, denied.text

        admin_hdrs = {**headers(accounts, ADMIN_EMAIL), "Content-Type": "text/csv"}
        report = await client.post(
            "/api/v1/pricing/prime-lanes/import?dry_run=false", headers=admin_hdrs, content=exported.content
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["errors"] == []
        assert (body["created"], body["updated"], body["deactivated"]) == (0, 0, 0), body
        assert await _lanes() == lanes_before
