"""
Delhivery-parity Pickup Request (Manifest / PUR) integration tests for B2C and B2B flows.
"""

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.manifests import Manifest, ManifestStatus
from app.models.pickups import PickupRequest, PickupStatus
from app.models.tenants import User, UserRole
from app.services.manifests import PICKED_SHIPMENT_STATUSES, ManifestService


@pytest.mark.asyncio
async def test_create_manifest_and_list():
    headers = {"X-Tenant-Slug": "logismart-test"}
    
    # 1. Create a shipment to assign to a manifest
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "order_reference_id": f"FWD-{str(uuid.uuid4())[:4]}",
            "shipment_type": "FORWARD",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "product_category": "ELECTRONICS",
            "is_carriers_risk": True,
            "new_pickup_address": {
                "name": "Warehouse A", "phone": "9999999999", "address_line1": "Road 1", "city": "Gurugram", "state": "HR", "pincode": "122001"
            },
            "new_delivery_address": {
                "name": "Customer B", "phone": "8888888888", "address_line1": "Road 2", "city": "Mumbai", "state": "MH", "pincode": "400001"
            },
            "packages": [{"length": 30.0, "breadth": 20.0, "height": 10.0, "weight": 2.0, "box_count": 1, "description": "Box 1"}],
            "payment_details": {
                "freight_payment_mode": "PREPAID", "is_cod": False, "cod_amount": 0.0, "shipment_total_value": 1000.0
            }
        }
        
        res = await client.post(f"{settings.API_V1_STR}/shipments", json=payload, headers=headers)
        assert res.status_code == 201, res.text
        shipment = res.json()
        shipment_id = shipment["id"]
        pickup_address_id = shipment["pickup_address"]["id"]
        
        # Transition DRAFT -> OPEN (Only OPEN shipments can be manifested)
        res = await client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json={"status": "OPEN", "comment": "Ready for pickup"},
            headers=headers
        )
        assert res.status_code == 200, res.text
        
        # 2. Create manifest
        manifest_payload = {
            "pickup_address_id": pickup_address_id,
            "scheduled_date": str(date.today()),
            "time_slot": "06:00 - 10:00",
            "is_blind_pickup": False,
            "total_boxes": 1,
            "shipment_ids": [shipment_id]
        }
        
        res = await client.post(f"{settings.API_V1_STR}/manifests/", json=manifest_payload, headers=headers)
        assert res.status_code == 201, res.text
        manifest = res.json()
        manifest_id = manifest["id"]
        
        # 3. Check if list manifests works
        res = await client.get(f"{settings.API_V1_STR}/manifests/", headers=headers)
        assert res.status_code == 200, res.text
        manifests = res.json()
        
        # Verify the created manifest is in the list
        found = next((m for m in manifests if m["id"] == manifest_id), None)
        assert found is not None
        assert found["expected_awbs"] == 1
        assert found["pickup_location_name"] == "Warehouse A"

        # 4. Verify shipment status transitioned to ASSIGNED
        res = await client.get(f"{settings.API_V1_STR}/shipments/{shipment_id}", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "ASSIGNED"

        # 5. Verify that attempting to manifest the same shipment again (since it is no longer OPEN) fails
        duplicate_manifest_payload = {
            "pickup_address_id": pickup_address_id,
            "scheduled_date": str(date.today()),
            "time_slot": "06:00 - 10:00",
            "is_blind_pickup": False,
            "total_boxes": 1,
            "shipment_ids": [shipment_id]
        }
        res = await client.post(f"{settings.API_V1_STR}/manifests/", json=duplicate_manifest_payload, headers=headers)
        assert res.status_code == 400
        assert "Only OPEN (Ready to Ship) shipments" in res.text


# =============================================================================
# Delhivery-parity Pickup Requests (PUR) for B2C and B2B flows
# =============================================================================

HEADERS = {"X-Tenant-Slug": "logismart-test"}
MANIFESTS_URL = f"{settings.API_V1_STR}/manifests"
SHIPMENTS_URL = f"{settings.API_V1_STR}/shipments"
PUR_NUMBER_LENGTH = 9


def _pickup_location(tag: str, pincode: str = "122001") -> dict:
    """A unique warehouse per test so assertions never collide with other tenant data."""
    return {
        "name": f"PUR Warehouse {tag}",
        "phone": "9000000001",
        "address_line1": f"Plot {tag}, Udyog Vihar",
        "city": "Gurugram",
        "state": "HR",
        "pincode": pincode,
    }


def _shipment_payload(pickup: dict, *, b2b: bool, box_count: int = 1, blind: bool = False) -> dict:
    """B2C parcel by default; B2B cargo is flagged through carrier's risk (shared classifier)."""
    return {
        "order_reference_id": f"PUR-{uuid.uuid4().hex[:6]}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "pickup_time_slot": "10:00 - 14:00",
        "product_category": "ELECTRONICS",
        "is_carriers_risk": b2b,
        "is_blind_pickup": blind,
        "estimated_box_count": box_count if blind else None,
        "new_pickup_address": dict(pickup),
        "new_delivery_address": {
            "name": "Consignee",
            "phone": "8888888888",
            "address_line1": "Road 2",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001",
        },
        "packages": (
            []
            if blind
            else [
                {
                    "length": 20.0,
                    "breadth": 20.0,
                    "height": 10.0,
                    "weight": 1.0,
                    "box_count": box_count,
                    "description": "Box",
                }
            ]
        ),
        "payment_details": {
            "freight_payment_mode": "PREPAID",
            "is_cod": False,
            "cod_amount": 0.0,
            "shipment_total_value": 1000.0,
        },
    }


async def _create_open_shipment(
    client: AsyncClient, pickup: dict, *, b2b: bool, box_count: int = 1, blind: bool = False
) -> dict:
    """Creates a shipment (each one gets its OWN pickup address snapshot) and moves it to OPEN."""
    res = await client.post(
        SHIPMENTS_URL,
        json=_shipment_payload(pickup, b2b=b2b, box_count=box_count, blind=blind),
        headers=HEADERS,
    )
    assert res.status_code == 201, res.text
    shipment = res.json()
    res = await client.patch(
        f"{SHIPMENTS_URL}/{shipment['id']}",
        json={"status": "OPEN", "comment": "Ready to ship"},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    return shipment


async def _create_pur(
    client: AsyncClient,
    pickup_address_id: str,
    shipment_ids: list,
    *,
    flow: str,
    blind: bool = False,
    total_boxes: int = 0,
):
    return await client.post(
        MANIFESTS_URL,
        json={
            "pickup_address_id": pickup_address_id,
            "scheduled_date": str(date.today()),
            "time_slot": "14:00 - 18:00",
            "service_flow": flow,
            "is_blind_pickup": blind,
            "total_boxes": total_boxes,
            "shipment_ids": shipment_ids,
        },
        headers=HEADERS,
    )


async def _shipment_status(client: AsyncClient, shipment_id: str) -> dict:
    res = await client.get(f"{SHIPMENTS_URL}/{shipment_id}", headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_b2c_pickup_request_create_and_rules():
    tag = uuid.uuid4().hex[:6]
    pickup = _pickup_location(tag)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship_a = await _create_open_shipment(client, pickup, b2b=False, box_count=2)
        ship_b = await _create_open_shipment(client, pickup, b2b=False, box_count=1)
        b2b_ship = await _create_open_shipment(client, pickup, b2b=True)
        location_id = ship_a["pickup_address"]["id"]
        # Snapshots: the second shipment has its own Address row for the same warehouse
        assert ship_b["pickup_address"]["id"] != location_id

        # Reject B2C blind pickups
        res = await _create_pur(client, location_id, [], flow="B2C", blind=True, total_boxes=5)
        assert res.status_code == 400
        assert "Blind pickups" in res.text

        # Reject B2C without shipments
        res = await _create_pur(client, location_id, [], flow="B2C")
        assert res.status_code == 400

        # Reject mixed-flow linking (B2B cargo inside a B2C PUR)
        res = await _create_pur(client, location_id, [ship_a["id"], b2b_ship["id"]], flow="B2C")
        assert res.status_code == 400
        assert "B2C pickup requests can only include B2C shipments" in res.text

        # Reject B2C shipment inside a B2B PUR
        res = await _create_pur(client, location_id, [ship_a["id"]], flow="B2B")
        assert res.status_code == 400
        assert "B2B pickup requests can only include B2B shipments" in res.text

        # Reject a shipment from another pickup location
        other = await _create_open_shipment(client, _pickup_location(f"{tag}x"), b2b=False)
        res = await _create_pur(client, location_id, [ship_a["id"], other["id"]], flow="B2C")
        assert res.status_code == 400
        assert "must be picked up from" in res.text

        # Happy path: number generated, boxes computed server-side, shipments ASSIGNED
        res = await _create_pur(
            client, location_id, [ship_a["id"], ship_b["id"]], flow="B2C", total_boxes=99
        )
        assert res.status_code == 201, res.text
        pur = res.json()
        assert pur["service_flow"] == "B2C"
        assert pur["status"] == "SCHEDULED"
        assert pur["pickup_request_number"].isdigit()
        assert len(pur["pickup_request_number"]) == PUR_NUMBER_LENGTH
        assert pur["total_boxes"] == 3
        assert pur["expected_awbs"] == 2
        assert pur["is_blind_pickup"] is False
        assert pickup["address_line1"] in pur["pickup_location_address"]
        for ship in (ship_a, ship_b):
            detail = await _shipment_status(client, ship["id"])
            assert detail["status"] == "ASSIGNED"
            assert detail["manifest_id"] == pur["id"]

        # service_flow list filter
        res = await client.get(MANIFESTS_URL, params={"service_flow": "B2C"}, headers=HEADERS)
        assert res.status_code == 200, res.text
        rows = res.json()
        assert any(m["id"] == pur["id"] for m in rows)
        assert all(m["service_flow"] == "B2C" for m in rows)
        res = await client.get(MANIFESTS_URL, params={"service_flow": "B2B"}, headers=HEADERS)
        assert all(m["id"] != pur["id"] for m in res.json())
        res = await client.get(
            MANIFESTS_URL,
            params={"status": "SCHEDULED", "scheduled_date": pur["scheduled_date"]},
            headers=HEADERS,
        )
        assert any(m["id"] == pur["id"] for m in res.json())


@pytest.mark.asyncio
async def test_b2b_pickup_request_blind_and_flow_check():
    pickup = _pickup_location(uuid.uuid4().hex[:6])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        b2b_ship = await _create_open_shipment(client, pickup, b2b=True, box_count=4)
        blind_lr = await _create_open_shipment(client, pickup, b2b=True, box_count=12, blind=True)
        location_id = b2b_ship["pickup_address"]["id"]

        # D-07: a B2B blind pickup without at least one linked LR is rejected with 400.
        res = await _create_pur(client, location_id, [], flow="B2B", blind=True, total_boxes=12)
        assert res.status_code == 400, res.text

        res = await _create_pur(
            client, location_id, [blind_lr["id"]], flow="B2B", blind=True, total_boxes=12
        )
        assert res.status_code == 201, res.text
        blind = res.json()
        assert blind["service_flow"] == "B2B"
        assert blind["total_boxes"] == 12
        assert len(blind["pickup_request_number"]) == PUR_NUMBER_LENGTH

        res = await _create_pur(client, location_id, [b2b_ship["id"]], flow="B2B")
        assert res.status_code == 201, res.text
        manifested = res.json()
        assert manifested["total_boxes"] == 4
        assert manifested["pickup_request_number"] != blind["pickup_request_number"]

        # Labels work because D-07 requires at least one linked LR on a blind pickup
        res = await client.get(f"{MANIFESTS_URL}/{blind['id']}/labels", headers=HEADERS)
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_eligible_shipments_filter_by_flow_and_location():
    tag = uuid.uuid4().hex[:6]
    pickup = _pickup_location(tag, pincode="122001")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        b2c_ship = await _create_open_shipment(client, pickup, b2b=False, box_count=2)
        b2c_ship_2 = await _create_open_shipment(client, pickup, b2b=False)
        b2b_ship = await _create_open_shipment(client, pickup, b2b=True)
        elsewhere = await _create_open_shipment(
            client, _pickup_location(f"{tag}y", pincode="122001"), b2b=False
        )
        location_id = b2c_ship["pickup_address"]["id"]

        res = await client.get(
            f"{MANIFESTS_URL}/eligible-shipments",
            params={"service_flow": "B2C", "pickup_address_id": location_id},
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        rows = {r["id"]: r for r in res.json()}
        assert b2c_ship["id"] in rows and b2c_ship_2["id"] in rows
        assert b2b_ship["id"] not in rows
        assert elsewhere["id"] not in rows
        row = rows[b2c_ship["id"]]
        assert row["package_count"] == 2
        assert row["total_weight_kg"] == 2.0
        assert row["delivery_pincode"] == "400001"
        assert row["tracking_id"] == b2c_ship["tracking_id"]

        res = await client.get(
            f"{MANIFESTS_URL}/eligible-shipments",
            params={"service_flow": "B2B", "pickup_address_id": location_id},
            headers=HEADERS,
        )
        ids = {r["id"] for r in res.json()}
        assert b2b_ship["id"] in ids and b2c_ship["id"] not in ids

        # Once linked, a shipment is no longer eligible
        res = await _create_pur(client, location_id, [b2c_ship["id"]], flow="B2C")
        assert res.status_code == 201, res.text
        res = await client.get(
            f"{MANIFESTS_URL}/eligible-shipments",
            params={"service_flow": "B2C", "pickup_address_id": location_id},
            headers=HEADERS,
        )
        assert b2c_ship["id"] not in {r["id"] for r in res.json()}


@pytest.mark.asyncio
async def test_pickup_candidates_and_add_to_existing():
    tag = uuid.uuid4().hex[:6]
    pickup = _pickup_location(tag)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _create_open_shipment(client, pickup, b2b=False)
        second = await _create_open_shipment(client, pickup, b2b=False, box_count=3)
        third = await _create_open_shipment(client, pickup, b2b=False)
        b2b_ship = await _create_open_shipment(client, pickup, b2b=True)
        elsewhere = await _create_open_shipment(client, _pickup_location(f"{tag}z"), b2b=False)
        location_id = first["pickup_address"]["id"]

        res = await _create_pur(client, location_id, [first["id"]], flow="B2C")
        assert res.status_code == 201, res.text
        pur = res.json()

        # Mixed flows -> 400
        res = await client.get(
            f"{MANIFESTS_URL}/pickup-candidates",
            params=[("shipment_ids", second["id"]), ("shipment_ids", b2b_ship["id"])],
            headers=HEADERS,
        )
        assert res.status_code == 400
        assert "mix B2C and B2B" in res.text

        # Different pickup locations -> 400
        res = await client.get(
            f"{MANIFESTS_URL}/pickup-candidates",
            params=[("shipment_ids", second["id"]), ("shipment_ids", elsewhere["id"])],
            headers=HEADERS,
        )
        assert res.status_code == 400

        # Valid selection -> today's scheduled PUR is a candidate
        res = await client.get(
            f"{MANIFESTS_URL}/pickup-candidates",
            params=[("shipment_ids", second["id"]), ("shipment_ids", third["id"])],
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["service_flow"] == "B2C"
        assert body["pickup_location_name"] == pickup["name"]
        assert any(c["id"] == pur["id"] for c in body["candidates"])

        # Add to existing: rejects other-flow shipment
        res = await client.post(
            f"{MANIFESTS_URL}/{pur['id']}/shipments",
            json={"shipment_ids": [b2b_ship["id"]]},
            headers=HEADERS,
        )
        assert res.status_code == 400

        res = await client.post(
            f"{MANIFESTS_URL}/{pur['id']}/shipments",
            json={"shipment_ids": [second["id"], third["id"]]},
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        updated = res.json()
        assert updated["expected_awbs"] == 3
        assert updated["total_boxes"] == 5
        assert (await _shipment_status(client, third["id"]))["status"] == "ASSIGNED"

        # Labels: one merged PDF for all linked shipments (A4 and thermal)
        res = await client.get(f"{MANIFESTS_URL}/{pur['id']}/labels", headers=HEADERS)
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/pdf"
        assert res.content.startswith(b"%PDF-")
        res = await client.get(
            f"{MANIFESTS_URL}/{pur['id']}/labels",
            params={"label_format": "thermal_4x2"},
            headers=HEADERS,
        )
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_out_for_pickup_and_not_picked_revert_shipments():
    pickup = _pickup_location(uuid.uuid4().hex[:6])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create_open_shipment(client, pickup, b2b=False)
        res = await _create_pur(client, ship["pickup_address"]["id"], [ship["id"]], flow="B2C")
        assert res.status_code == 201, res.text
        pur = res.json()

        # Not-picked requires a reason
        res = await client.post(
            f"{MANIFESTS_URL}/{pur['id']}/not-picked", json={"failure_reason": ""}, headers=HEADERS
        )
        assert res.status_code == 422

        res = await client.post(f"{MANIFESTS_URL}/{pur['id']}/out-for-pickup", headers=HEADERS)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "OUT_FOR_PICKUP"

        # OUT_FOR_PICKUP cannot transition to OUT_FOR_PICKUP again
        res = await client.post(f"{MANIFESTS_URL}/{pur['id']}/out-for-pickup", headers=HEADERS)
        assert res.status_code == 400

        reason = "Shipment not ready for pickup - Geofenced"
        res = await client.post(
            f"{MANIFESTS_URL}/{pur['id']}/not-picked",
            json={"failure_reason": reason},
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "NOT_PICKED"
        assert body["failure_reason"] == reason
        assert body["expected_awbs"] == 0

        detail = await _shipment_status(client, ship["id"])
        assert detail["status"] == "OPEN"
        assert detail["manifest_id"] is None

        # Terminal: cannot cancel a NOT_PICKED pickup
        res = await client.post(f"{MANIFESTS_URL}/{pur['id']}/cancel", headers=HEADERS)
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_customer_cannot_run_admin_pickup_transitions():
    pickup = _pickup_location(uuid.uuid4().hex[:6])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ship = await _create_open_shipment(client, pickup, b2b=False)
        res = await _create_pur(client, ship["pickup_address"]["id"], [ship["id"]], flow="B2C")
        assert res.status_code == 201, res.text
        pur = res.json()

        admin_override = app.dependency_overrides[get_current_active_user]
        admin = await admin_override()
        customer = User(**{**admin.model_dump(), "id": uuid.uuid4(), "role": UserRole.customer})

        async def _as_customer():
            return customer

        app.dependency_overrides[get_current_active_user] = _as_customer
        try:
            res = await client.post(f"{MANIFESTS_URL}/{pur['id']}/out-for-pickup", headers=HEADERS)
            assert res.status_code == 403
            res = await client.post(
                f"{MANIFESTS_URL}/{pur['id']}/not-picked",
                json={"failure_reason": "No show"},
                headers=HEADERS,
            )
            assert res.status_code == 403
            res = await client.get(MANIFESTS_URL, headers=HEADERS)
            assert all(m["id"] != pur["id"] for m in res.json())
            res = await client.get(f"{MANIFESTS_URL}/{pur['id']}/labels", headers=HEADERS)
            assert res.status_code == 403
        finally:
            app.dependency_overrides[get_current_active_user] = admin_override


def test_picked_awbs_counts_all_post_pickup_statuses():
    """Once a manifest is picked, shipments that later enter OFD/NDR/RTO/LOST still count as picked."""
    post_pickup = [
        PickupStatus.IN_TRANSIT,
        PickupStatus.OUT_FOR_DELIVERY,
        PickupStatus.EXCEPTION,
        PickupStatus.COMPLETED,
        PickupStatus.RTO_INITIATED,
        PickupStatus.RTO_IN_TRANSIT,
        PickupStatus.RTO_DELIVERED,
        PickupStatus.LOST,
    ]
    for status in post_pickup:
        assert status in PICKED_SHIPMENT_STATUSES

    tenant_id = uuid.uuid4()
    manifest = Manifest(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        pickup_address_id=uuid.uuid4(),
        scheduled_date=date.today(),
        time_slot="10:00 - 14:00",
        status=ManifestStatus.PICKED,
        total_boxes=len(post_pickup),
    )
    manifest.pickups = [
        PickupRequest(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            tracking_id=f"LOGISMART-TEST-P{idx}",
            order_reference_id=f"REF-{idx}",
            status=status,
            requested_pickup_date=date.today(),
        )
        for idx, status in enumerate(post_pickup + [PickupStatus.ASSIGNED])
    ]
    response = ManifestService._to_response(manifest, None)
    assert response["expected_awbs"] == len(post_pickup) + 1
    assert response["picked_awbs"] == len(post_pickup)

