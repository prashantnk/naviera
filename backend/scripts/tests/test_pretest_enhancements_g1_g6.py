import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.config import settings
from app.core.dependencies import (
    get_current_active_user,
    get_tenant_from_header,
)
from app.main import app
from app.models.wallet import UserWallet, WalletTransaction, WalletTxnStatus
from app.services.wallet import WalletService

HEADERS = {"X-Tenant-Slug": "naviera"}
SHIPMENTS_URL = f"{settings.API_V1_STR}/shipments"
MANIFESTS_URL = f"{settings.API_V1_STR}/manifests"
WALLET_AUDIT_URL = f"{settings.API_V1_STR}/wallet/audit-integrity"


def _build_shipment_payload(
    *,
    shipment_type: str = "FORWARD",
    pickup_address_id: str | None = None,
    box_count: int = 1,
    qc_required: bool = False,
    qc_notes: str | None = None,
    reason_for_return: str | None = None,
) -> dict:
    tag = uuid.uuid4().hex[:6].upper()
    payload: dict = {
        "order_reference_id": f"{shipment_type[:3]}-{tag}",
        "shipment_type": shipment_type,
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "pickup_time_slot": "10:00 - 14:00",
        "product_category": "ELECTRONICS",
        "is_carriers_risk": False,
        "qc_required": qc_required,
        "qc_notes": qc_notes,
        "reason_for_return": reason_for_return,
        "new_delivery_address": {
            "name": f"Consignee {tag}",
            "phone": "9888877776",
            "address_line1": "42 Residency Road",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001",
        },
        "packages": [
            {
                "length": 20.0,
                "breadth": 15.0,
                "height": 10.0,
                "weight": 1.0,
                "box_count": box_count,
                "description": f"Parcel {tag}",
            }
        ],
        "payment_details": {
            "freight_payment_mode": "PREPAID",
            "is_cod": False,
            "cod_amount": 0.0,
            "shipment_total_value": 1200.0,
        },
    }
    if pickup_address_id:
        payload["pickup_address_id"] = pickup_address_id
    else:
        payload["new_pickup_address"] = {
            "name": f"Origin Hub {tag}",
            "phone": "9999988887",
            "address_line1": f"Plot {tag}, Phase 2",
            "city": "Delhi",
            "state": "DL",
            "pincode": "110001",
        }
    return payload


@pytest.mark.asyncio
async def test_g1_partial_pickup_manifest_dispatch_detaches_unpicked_awbs():
    """G1: Dispatching a manifest with a subset of AWBs marks picked AWBs IN_TRANSIT and releases unpicked AWBs back to OPEN."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Create Shipment 1 (2 boxes) and transition DRAFT -> OPEN
        res1 = await client.post(
            SHIPMENTS_URL,
            json=_build_shipment_payload(box_count=2),
            headers=HEADERS,
        )
        assert res1.status_code == 201, res1.text
        s1 = res1.json()
        s1_id = s1["id"]
        pickup_addr_id = s1["pickup_address"]["id"]

        patch1 = await client.patch(
            f"{SHIPMENTS_URL}/{s1_id}",
            json={"status": "OPEN", "comment": "Ready for pickup"},
            headers=HEADERS,
        )
        assert patch1.status_code == 200, patch1.text

        # 2. Create Shipment 2 (1 box) at the same pickup warehouse and transition DRAFT -> OPEN
        res2 = await client.post(
            SHIPMENTS_URL,
            json=_build_shipment_payload(
                pickup_address_id=pickup_addr_id, box_count=1
            ),
            headers=HEADERS,
        )
        assert res2.status_code == 201, res2.text
        s2 = res2.json()
        s2_id = s2["id"]

        patch2 = await client.patch(
            f"{SHIPMENTS_URL}/{s2_id}",
            json={"status": "OPEN", "comment": "Ready for pickup"},
            headers=HEADERS,
        )
        assert patch2.status_code == 200, patch2.text

        # 3. Create Pickup Manifest with both shipments
        manifest_res = await client.post(
            f"{MANIFESTS_URL}/",
            json={
                "pickup_address_id": pickup_addr_id,
                "scheduled_date": str(date.today()),
                "time_slot": "10:00 - 14:00",
                "is_blind_pickup": False,
                "service_flow": "B2C",
                "total_boxes": 3,
                "shipment_ids": [s1_id, s2_id],
            },
            headers=HEADERS,
        )
        assert manifest_res.status_code == 201, manifest_res.text
        manifest = manifest_res.json()
        manifest_id = manifest["id"]
        assert manifest["expected_awbs"] == 2
        assert len(manifest["shipments"]) == 2

        # 4. Empty picked_shipment_ids list must be rejected with HTTP 400
        empty_res = await client.post(
            f"{MANIFESTS_URL}/{manifest_id}/dispatch",
            json={"picked_shipment_ids": []},
            headers=HEADERS,
        )
        assert empty_res.status_code == 400

        # 5. Dispatch with ONLY s1_id picked (partial pickup)
        dispatch_res = await client.post(
            f"{MANIFESTS_URL}/{manifest_id}/dispatch",
            json={"picked_shipment_ids": [s1_id]},
            headers=HEADERS,
        )
        assert dispatch_res.status_code == 200, dispatch_res.text
        dispatched = dispatch_res.json()
        assert dispatched["status"] == "PICKED"
        assert dispatched["expected_awbs"] == 1
        assert dispatched["picked_awbs"] == 1
        assert dispatched["total_boxes"] == 2
        assert [item["id"] for item in dispatched["shipments"]] == [s1_id]

        # 6. Verify s1 is IN_TRANSIT with a 6-digit delivery_otp
        s1_after = (
            await client.get(f"{SHIPMENTS_URL}/{s1_id}", headers=HEADERS)
        ).json()
        assert s1_after["status"] == "IN_TRANSIT"
        assert s1_after["manifest_id"] == manifest_id
        assert s1_after["delivery_otp"] is not None
        assert len(s1_after["delivery_otp"]) == 6

        # 7. Verify s2 was detached back to OPEN (Ready to Ship) with manifest_id == None
        s2_after = (
            await client.get(f"{SHIPMENTS_URL}/{s2_id}", headers=HEADERS)
        ).json()
        assert s2_after["status"] == "OPEN"
        assert s2_after["manifest_id"] is None


@pytest.mark.asyncio
async def test_g2_list_shipments_forward_vs_reverse_filter():
    """G2: GET /api/v1/shipments?shipment_type=FORWARD|REVERSE filters forward vs reverse (DTO) orders."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        fwd_res = await client.post(
            SHIPMENTS_URL,
            json=_build_shipment_payload(shipment_type="FORWARD"),
            headers=HEADERS,
        )
        assert fwd_res.status_code == 201, fwd_res.text
        fwd_id = fwd_res.json()["id"]

        rev_res = await client.post(
            SHIPMENTS_URL,
            json=_build_shipment_payload(
                shipment_type="REVERSE",
                qc_required=True,
                qc_notes="Check box seal",
                reason_for_return="Size exchange",
            ),
            headers=HEADERS,
        )
        assert rev_res.status_code == 201, rev_res.text
        rev_id = rev_res.json()["id"]

        list_fwd = await client.get(
            f"{SHIPMENTS_URL}?shipment_type=FORWARD&size=50",
            headers=HEADERS,
        )
        assert list_fwd.status_code == 200, list_fwd.text
        fwd_items = list_fwd.json()["items"]
        assert any(item["id"] == fwd_id for item in fwd_items)
        assert all(item["shipment_type"] == "FORWARD" for item in fwd_items)

        list_rev = await client.get(
            f"{SHIPMENTS_URL}?shipment_type=REVERSE&size=50",
            headers=HEADERS,
        )
        assert list_rev.status_code == 200, list_rev.text
        rev_items = list_rev.json()["items"]
        assert any(item["id"] == rev_id for item in rev_items)
        assert all(item["shipment_type"] == "REVERSE" for item in rev_items)


@pytest.mark.asyncio
async def test_g3_reverse_doorstep_qc_failed_detaches_manifest_and_logs_timeline():
    """G3: Failing doorstep QC on a REVERSE return transitions status to QC_FAILED, detaches any manifest, and records public timeline entry."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        rev_res = await client.post(
            SHIPMENTS_URL,
            json=_build_shipment_payload(
                shipment_type="REVERSE",
                qc_required=True,
                qc_notes="Verify IMEI & unbroken security seal",
                reason_for_return="Customer return - damaged display",
            ),
            headers=HEADERS,
        )
        assert rev_res.status_code == 201, rev_res.text
        rev = rev_res.json()
        rev_id = rev["id"]
        pickup_addr_id = rev["pickup_address"]["id"]

        # Transition DRAFT -> OPEN
        open_res = await client.patch(
            f"{SHIPMENTS_URL}/{rev_id}",
            json={"status": "OPEN", "comment": "Return approved for pickup"},
            headers=HEADERS,
        )
        assert open_res.status_code == 200, open_res.text

        # Link to a SCHEDULED manifest (transitions shipment to ASSIGNED)
        manifest_res = await client.post(
            f"{MANIFESTS_URL}/",
            json={
                "pickup_address_id": pickup_addr_id,
                "scheduled_date": str(date.today()),
                "time_slot": "10:00 - 14:00",
                "is_blind_pickup": False,
                "service_flow": "B2C",
                "total_boxes": 1,
                "shipment_ids": [rev_id],
            },
            headers=HEADERS,
        )
        assert manifest_res.status_code == 201, manifest_res.text

        # Field executive fails doorstep QC
        qc_fail_res = await client.patch(
            f"{SHIPMENTS_URL}/{rev_id}",
            json={
                "status": "QC_FAILED",
                "comment": "Security seal tampered and screen cracked",
                "is_public": True,
            },
            headers=HEADERS,
        )
        assert qc_fail_res.status_code == 200, qc_fail_res.text
        updated = qc_fail_res.json()
        assert updated["status"] == "QC_FAILED"
        assert updated["manifest_id"] is None

        timeline_res = await client.get(
            f"{SHIPMENTS_URL}/{rev_id}/timeline", headers=HEADERS
        )
        assert timeline_res.status_code == 200, timeline_res.text
        timeline = timeline_res.json()
        assert any(
            "Doorstep QC Failed — Return Rejected at Pickup"
            in (ev.get("summary") or "")
            and "Security seal tampered and screen cracked"
            in (ev.get("comment") or "")
            for ev in timeline
        )


@pytest.mark.asyncio
async def test_g6_wallet_and_lifecycle_integrity_audit_endpoint(db_session):
    """G6: GET /api/v1/wallet/audit-integrity verifies wallet ledger invariants and detects balance tampering."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(WALLET_AUDIT_URL, headers=HEADERS)
        assert res.status_code == 200, res.text
        initial_report = res.json()
        assert "passed" in initial_report
        assert "wallets_checked" in initial_report
        assert "transactions_checked" in initial_report
        assert "shipments_checked" in initial_report
        assert "invoices_checked" in initial_report
        assert "remittances_checked" in initial_report
        assert isinstance(initial_report["discrepancies"], list)

        # Find the active test user's wallet and introduce a temporary unbacked +123.45 drift
        active_tenant = await app.dependency_overrides[get_tenant_from_header]()
        active_user = await app.dependency_overrides[get_current_active_user]()
        tenant_id = active_tenant.id
        user_id = active_user.id
        wallet = (
            await db_session.exec(
                select(UserWallet).where(
                    UserWallet.tenant_id == tenant_id,
                    UserWallet.user_id == user_id,
                )
            )
        ).one()
        txns = list(
            (
                await db_session.exec(
                    select(WalletTransaction)
                    .where(
                        WalletTransaction.tenant_id == tenant_id,
                        WalletTransaction.user_id == user_id,
                    )
                    .order_by(
                        WalletTransaction.created_at.asc(),
                        WalletTransaction.id.asc(),
                    )
                )
            ).all()
        )
        completed_txns = [
            t for t in txns if t.status == WalletTxnStatus.COMPLETED
        ]
        true_ledger_balance = round(
            sum(WalletService._signed_txn_amount(t) for t in completed_txns), 2
        )
        original_balance = float(wallet.balance)

        try:
            # First set wallet.balance to true_ledger_balance + 123.45 so it is guaranteed out-of-sync
            wallet.balance = round(true_ledger_balance + 123.45, 2)
            db_session.add(wallet)
            await db_session.flush()

            tampered_res = await client.get(WALLET_AUDIT_URL, headers=HEADERS)
            assert tampered_res.status_code == 200, tampered_res.text
            tampered_report = tampered_res.json()
            assert tampered_report["passed"] is False
            assert tampered_report["discrepancy_count"] >= 1
            assert any(
                d["category"] == "WALLET_BALANCE"
                and d["entity_id"] == str(wallet.id)
                for d in tampered_report["discrepancies"]
            )
        finally:
            wallet.balance = original_balance
            db_session.add(wallet)
            await db_session.flush()
