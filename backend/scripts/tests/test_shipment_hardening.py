"""
Shipment lifecycle hardening (Phase O.8, Job A.5 production-readiness fixes).

1. New bookings are created as OPEN (Ready to Ship).
2. Appointment updates only release APPOINTMENT_NEEDED exceptions.
3. Status-only updates never re-price or touch the wallet.
4. COD with add_shipping_to_cod no longer blocks later status / POD updates.
5. Admin cancellation via PATCH refunds prepaid freight and releases the Pickup Request.
6. COD settlement ignores parcels that were returned to origin (RTO).
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import func, select

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.main import app
from app.models.pickups import NdrExceptionReason, PickupRequest, PickupStatus
from app.models.wallet import WalletTransaction, WalletTxnType
from app.repositories.wallet import WalletRepository

HEADERS = {"X-Tenant-Slug": "logismart-test"}
SHIPMENTS_URL = f"{settings.API_V1_STR}/shipments"
MANIFESTS_URL = f"{settings.API_V1_STR}/manifests"
GOODS_VALUE = 1000.0


def _payload(*, b2b: bool = False, cod: bool = False) -> dict:
    tag = uuid.uuid4().hex[:8]
    return {
        "order_reference_id": f"HARD-{tag}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "pickup_time_slot": "10:00 - 14:00",
        "product_category": "ELECTRONICS",
        "is_carriers_risk": b2b,
        "new_pickup_address": {
            "name": f"Hardening WH {tag}",
            "phone": "9000000004",
            "address_line1": f"Plot {tag}",
            "city": "Gurugram",
            "state": "HR",
            "pincode": "122001",
        },
        "new_delivery_address": {
            "name": "Hardening Consignee",
            "phone": "8888888888",
            "address_line1": "Road 3",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001",
        },
        "packages": [
            {"length": 20.0, "breadth": 20.0, "height": 10.0, "weight": 1.5, "box_count": 1}
        ],
        "payment_details": {
            "freight_payment_mode": "PREPAID",
            "is_cod": cod,
            "cod_amount": GOODS_VALUE if cod else 0.0,
            "add_shipping_to_cod": cod,
            "shipment_total_value": GOODS_VALUE,
        },
    }


async def _create(client: AsyncClient, **kwargs) -> dict:
    res = await client.post(SHIPMENTS_URL, json=_payload(**kwargs), headers=HEADERS)
    assert res.status_code == 201, res.text
    return res.json()


async def _patch(client: AsyncClient, shipment_id: str, body: dict, expected: int = 200) -> dict:
    res = await client.patch(f"{SHIPMENTS_URL}/{shipment_id}", json=body, headers=HEADERS)
    assert res.status_code == expected, res.text
    return res.json()


async def _set_status(db_session, shipment_id: str, new_status: PickupStatus) -> None:
    shipment = await db_session.get(PickupRequest, uuid.UUID(shipment_id))
    shipment.status = new_status
    db_session.add(shipment)
    await db_session.flush()


async def _txn_count(db_session, shipment_id: str) -> int:
    return (
        await db_session.exec(
            select(func.count()).select_from(WalletTransaction).where(
                WalletTransaction.shipment_id == uuid.UUID(shipment_id)
            )
        )
    ).one()


@pytest.mark.asyncio
async def test_new_booking_is_ready_to_ship():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client)
        assert ship["status"] == "OPEN"


@pytest.mark.asyncio
async def test_status_only_updates_do_not_reprice_or_touch_wallet(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client, b2b=True)
        booked_total = ship["payment_details"]["total_logistics_cost"]
        booked_breakdown = ship["payment_details"]["pricing_breakdown"]
        txns_before = await _txn_count(db_session, ship["id"])

        assigned = await _patch(client, ship["id"], {"status": "ASSIGNED", "comment": "PUR"})
        in_transit = await _patch(client, ship["id"], {"status": "IN_TRANSIT", "comment": "Picked"})
        for body in (assigned, in_transit):
            assert body["payment_details"]["total_logistics_cost"] == booked_total
            assert body["payment_details"]["pricing_breakdown"] == booked_breakdown
        assert await _txn_count(db_session, ship["id"]) == txns_before


@pytest.mark.asyncio
async def test_cod_with_shipping_allows_status_and_pod_updates(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client, cod=True)
        assert ship["door_collectible"] > GOODS_VALUE  # goods + freight
        await _patch(client, ship["id"], {"status": "ASSIGNED", "comment": "PUR"})
        in_transit = await _patch(client, ship["id"], {"status": "IN_TRANSIT", "comment": "Picked"})
        delivered = await _patch(
            client,
            ship["id"],
            {
                "status": "COMPLETED",
                "comment": "Delivered",
                "pod_received_by": "Front desk",
                "delivery_otp": in_transit["delivery_otp"],
            },
        )
        assert delivered["status"] == "COMPLETED"

        # Editing COD after delivery is frozen and rejected with 400 (H-9).
        await _patch(
            client,
            ship["id"],
            {
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": True,
                    "cod_amount": GOODS_VALUE + 500.0,
                    "add_shipping_to_cod": False,
                    "shipment_total_value": GOODS_VALUE,
                }
            },
            expected=400,
        )


@pytest.mark.asyncio
async def test_appointment_update_only_clears_appointment_needed(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        charged = await _create(client, b2b=True)
        appointment = await _create(client, b2b=True)
        for ship in (charged, appointment):
            await _set_status(db_session, ship["id"], PickupStatus.IN_TRANSIT)
        await _patch(
            client,
            charged["id"],
            {"status": "EXCEPTION", "ndr_reason": NdrExceptionReason.FREIGHT_COLLECTION.value, "charge_amount": 99.0},
        )
        await _patch(
            client,
            appointment["id"],
            {"status": "EXCEPTION", "ndr_reason": NdrExceptionReason.APPOINTMENT_NEEDED.value},
        )
        start = datetime.now(timezone.utc) + timedelta(days=1)
        slot = {"appointment_start": start.isoformat(), "appointment_end": (start + timedelta(hours=2)).isoformat()}

        res = await client.patch(f"{SHIPMENTS_URL}/{charged['id']}/appointment", json=slot, headers=HEADERS)
        assert res.status_code == 400, res.text
        assert "FREIGHT_COLLECTION" in res.json()["detail"]

        res = await client.patch(f"{SHIPMENTS_URL}/{appointment['id']}/appointment", json=slot, headers=HEADERS)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "IN_TRANSIT"
        assert res.json()["ndr_reason"] is None


@pytest.mark.asyncio
async def test_admin_cancel_via_patch_refunds_and_releases_pickup_request(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create(client)
        res = await client.post(
            MANIFESTS_URL,
            json={
                "pickup_address_id": ship["pickup_address"]["id"],
                "scheduled_date": str(date.today()),
                "time_slot": "14:00 - 18:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "total_boxes": 0,
                "shipment_ids": [ship["id"]],
            },
            headers=HEADERS,
        )
        assert res.status_code == 201, res.text
        linked = await client.get(f"{SHIPMENTS_URL}/{ship['id']}", headers=HEADERS)
        assert linked.json()["manifest_id"] is not None

        cancelled = await _patch(client, ship["id"], {"status": "CANCELLED", "comment": "Ops cancel"})
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["manifest_id"] is None
        refund = (
            await db_session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.shipment_id == uuid.UUID(ship["id"]),
                    WalletTransaction.txn_type == WalletTxnType.REFUND.value,
                )
            )
        ).first()
        assert refund is not None
        assert round(float(refund.amount), 2) == round(ship["payment_details"]["total_logistics_cost"], 2)


@pytest.mark.asyncio
async def test_cod_settlement_skips_returned_parcels(db_session):
    admin = await app.dependency_overrides[get_current_active_user]()
    tenant = await app.dependency_overrides[get_tenant_from_header]()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        delivered = await _create(client, cod=True)
        returned = await _create(client, cod=True)
        in_transit_map = {}
        for ship in (delivered, returned):
            await _patch(client, ship["id"], {"status": "ASSIGNED", "comment": "PUR"})
            in_transit_map[ship["id"]] = await _patch(
                client, ship["id"], {"status": "IN_TRANSIT", "comment": "Picked"}
            )
        await _patch(client, returned["id"], {"status": "RTO_INITIATED", "comment": "Refused"})
        # RTO parcels cannot transition to COMPLETED (400) and are excluded from COD settlement.
        await _patch(
            client,
            returned["id"],
            {
                "status": "COMPLETED",
                "pod_received_by": "Receiver",
                "delivery_otp": in_transit_map[returned["id"]]["delivery_otp"],
            },
            expected=400,
        )
        await _patch(
            client,
            delivered["id"],
            {
                "status": "COMPLETED",
                "pod_received_by": "Receiver",
                "delivery_otp": in_transit_map[delivered["id"]]["delivery_otp"],
            },
        )

    unsettled = await WalletRepository(db_session).get_unsettled_completed_cod_shipments(
        admin.id, tenant.id
    )
    ids = {str(s.id) for s in unsettled}
    assert delivered["id"] in ids
    assert returned["id"] not in ids
