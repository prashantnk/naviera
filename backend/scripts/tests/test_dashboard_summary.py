"""
Dashboard summary endpoint (`GET /api/v1/dashboard/summary`) integration tests:
stage keys, live counts, and customer scoping on `logismart-test`.
"""

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.tenants import User, UserRole

HEADERS = {"X-Tenant-Slug": "logismart-test"}
SUMMARY_URL = f"{settings.API_V1_STR}/dashboard/summary"
SHIPMENTS_URL = f"{settings.API_V1_STR}/shipments"
MANIFESTS_URL = f"{settings.API_V1_STR}/manifests"

B2C_STAGE_KEYS = {
    "to_be_shipped",
    "awaiting_pickup",
    "in_transit",
    "out_for_delivery",
    "ndr_exceptions",
    "delivered",
    "rto",
}
B2B_STAGE_KEYS = {
    "lrs_manifested",
    "in_transit",
    "out_for_delivery",
    "exceptions",
    "consignee_unreachable",
    "delivered",
    "rto",
}
PERFORMANCE_KEYS = {
    "successful_delivery_rate",
    "first_attempt_delivery_rate",
    "avg_days_to_first_attempt",
    "on_time_delivery_rate",
}


def _b2c_payload(tag: str) -> dict:
    return {
        "order_reference_id": f"DASH-{tag}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "pickup_time_slot": "10:00 - 14:00",
        "product_category": "ELECTRONICS",
        "new_pickup_address": {
            "name": f"Dash WH {tag}",
            "phone": "9000000002",
            "address_line1": f"Dash Road {tag}",
            "city": "Pune",
            "state": "MH",
            "pincode": "411001",
        },
        "new_delivery_address": {
            "name": "Dash Consignee",
            "phone": "8888888888",
            "address_line1": "Road 9",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001",
        },
        "packages": [
            {"length": 10.0, "breadth": 10.0, "height": 10.0, "weight": 1.0, "box_count": 1}
        ],
        "payment_details": {
            "freight_payment_mode": "PREPAID",
            "is_cod": False,
            "cod_amount": 0.0,
            "shipment_total_value": 500.0,
        },
    }


async def _summary(client: AsyncClient, flow: str, days: int = 30) -> dict:
    res = await client.get(SUMMARY_URL, params={"service_flow": flow, "days": days}, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


def _assert_shape(body: dict, flow: str, days: int) -> None:
    assert body["service_flow"] == flow
    assert body["days"] == days
    assert body["generated_at"]
    assert set(body["performance"].keys()) == PERFORMANCE_KEYS
    assert body["performance"]["on_time_delivery_rate"] is None
    assert len(body["daily_series"]) == days
    for point in body["daily_series"]:
        assert set(point.keys()) == {"date", "in_transit", "delivered", "returned"}
    expected_keys = B2B_STAGE_KEYS if flow == "B2B" else B2C_STAGE_KEYS
    assert set(body["stages"].keys()) == expected_keys
    for metric in body["performance"].values():
        assert metric is None or isinstance(metric, (int, float))


@pytest.mark.asyncio
async def test_dashboard_summary_shape_and_live_counts():
    tag = uuid.uuid4().hex[:6]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = await _summary(client, "B2C")
        _assert_shape(before, "B2C", 30)
        assert before["appointments"] is None

        b2b = await _summary(client, "B2B", days=7)
        _assert_shape(b2b, "B2B", 7)
        assert set(b2b["appointments"].keys()) == {"needed", "at_risk", "booked"}

        # Create an OPEN B2C shipment -> to_be_shipped +1
        res = await client.post(SHIPMENTS_URL, json=_b2c_payload(tag), headers=HEADERS)
        assert res.status_code == 201, res.text
        shipment = res.json()
        res = await client.patch(
            f"{SHIPMENTS_URL}/{shipment['id']}",
            json={"status": "OPEN", "comment": "Ready"},
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        after_open = await _summary(client, "B2C")
        assert after_open["stages"]["to_be_shipped"] == before["stages"]["to_be_shipped"] + 1

        # Pickup + dispatch -> IN_TRANSIT and today's daily in_transit bucket increments
        res = await client.post(
            MANIFESTS_URL,
            json={
                "pickup_address_id": shipment["pickup_address"]["id"],
                "scheduled_date": str(date.today()),
                "time_slot": "10:00 - 14:00",
                "service_flow": "B2C",
                "shipment_ids": [shipment["id"]],
            },
            headers=HEADERS,
        )
        assert res.status_code == 201, res.text
        after_assign = await _summary(client, "B2C")
        assert after_assign["stages"]["awaiting_pickup"] == before["stages"]["awaiting_pickup"] + 1

        res = await client.post(f"{MANIFESTS_URL}/{res.json()['id']}/dispatch", headers=HEADERS)
        assert res.status_code == 200, res.text
        after_dispatch = await _summary(client, "B2C")
        assert after_dispatch["stages"]["in_transit"] == before["stages"]["in_transit"] + 1
        assert (
            after_dispatch["daily_series"][-1]["in_transit"]
            == before["daily_series"][-1]["in_transit"] + 1
        )

        res = await client.get(SUMMARY_URL, params={"service_flow": "B2C", "days": 5}, headers=HEADERS)
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_dashboard_summary_customer_scoping():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_override = app.dependency_overrides[get_current_active_user]
        admin = await admin_override()
        customer = User(**{**admin.model_dump(), "id": uuid.uuid4(), "role": UserRole.customer})

        async def _as_customer():
            return customer

        app.dependency_overrides[get_current_active_user] = _as_customer
        try:
            for flow in ("B2C", "B2B"):
                body = await _summary(client, flow, days=14)
                _assert_shape(body, flow, 14)
                assert all(v == 0 for v in body["stages"].values())
                assert all(v is None for v in body["performance"].values())
                assert all(
                    p["in_transit"] == 0 and p["delivered"] == 0 and p["returned"] == 0
                    for p in body["daily_series"]
                )
                if flow == "B2B":
                    assert body["appointments"] == {"needed": 0, "at_risk": 0, "booked": 0}
        finally:
            app.dependency_overrides[get_current_active_user] = admin_override
