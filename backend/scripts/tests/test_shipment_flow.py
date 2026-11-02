from datetime import date, timedelta
import uuid

from app.core.config import settings
from app.main import app
from httpx import ASGITransport, AsyncClient
import pytest
from supabase import Client, create_client

# --- Configuration ---
TEST_USER_EMAIL = "naviera_test_user@naviera.com"
TEST_USER_PASSWORD = "NavieraTestUser"
TENANT_SLUG = "naviera"
API_BASE_URL = "http://localhost:8000"


def get_auth_token():
    """
    Authenticates with Supabase to get a valid JWT.
    Reused from test_auth_flow.py
    """
    print(f"🔐 Authenticating as '{TEST_USER_EMAIL}'")
    try:
        supabase: Client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_ANON_KEY,
        )
        response = supabase.auth.sign_in_with_password(
            {"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
        )
        print("✅ Auth Successful.")
        return response.session.access_token  # type: ignore
    except Exception as e:
        print(f"❌ Auth Failed: {e}")
        exit(1)


def generate_dummy_payload():
    """
    Creates a rich JSON payload with New Addresses, Packages, and Payments.
    """
    random_id = str(uuid.uuid4())[:8].upper()

    return {
        "order_reference_id": f"ORD-{random_id}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today() + timedelta(days=1)),
        "pickup_time_slot": "06:00 - 10:00",
        "product_category": "ELECTRONICS",
        "new_pickup_address": {
            "name": "Warehouse Alpha",
            "phone": "+919988776655",
            "email": "warehouse@naviera.com",
            "address_line1": "Plot 42, Hitech City",
            "city": "Hyderabad",
            "state": "Telangana",
            "pincode": "500081",
            "country": "IN",
        },
        "new_delivery_address": {
            "name": "John Doe",
            "phone": "+919876543210",
            "address_line1": "Flat 101, Palm Springs",
            "city": "Bangalore",
            "state": "Karnataka",
            "pincode": "560001",
            "country": "IN",
            "is_saved": False,
            "address_type": "CUSTOMER",
        },
        "packages": [
            {
                "length": 30.0,
                "breadth": 20.0,
                "height": 10.0,
                "weight": 1.5,
                "box_count": 1,
                "description": "Laptop Box",
            },
            {
                "length": 15.0,
                "breadth": 10.0,
                "height": 5.0,
                "weight": 0.5,
                "box_count": 2,
                "description": "Chargers",
            },
        ],
        "payment_details": {
            "invoice_numbers": ["INV-001", "INV-002"],
            "eway_bill_numbers": ["123456789012"],
            "freight_payment_mode": "PREPAID",
            "is_cod": False,
            "cod_amount": 0.0,
            "add_shipping_to_cod": False,
            "shipment_value": 50000.00,
            "shipment_tax_value": 0.0,
            "shipment_total_value": 50000.00,
            "base_freight": 1230.00,
            "tax_amount": 248.04,
            "total_logistics_cost": 1626.04,
        },
        "documents": [
            {
                "document_type": "GST_INVOICE",
                "file_url": "https://s3.aws.com/naviera/inv-123.pdf",
                "file_name": "invoice.pdf",
            }
        ],
    }


@pytest.mark.asyncio
async def test_shipment_flow():
    payload = generate_dummy_payload()
    print("\n📦 Sending Shipment Creation Request")

    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{settings.API_V1_STR}/shipments",
            headers=headers,
            json=payload,
        )

        assert (
            response.status_code == 201
        ), f"Failed to create shipment: {response.text}"

        data = response.json()
        assert data["id"] is not None
        assert data["status"] == "OPEN"  # Ready to Ship immediately (Delhivery parity)
        assert data["pickup_address"]["id"] is not None
        assert len(data["packages"]) == 2


@pytest.mark.asyncio
async def test_create_blind_pickup_success():
    payload = generate_dummy_payload()
    payload["is_blind_pickup"] = True
    payload["estimated_box_count"] = 5
    payload["packages"] = []

    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{settings.API_V1_STR}/shipments",
            headers=headers,
            json=payload,
        )
        assert (
            response.status_code == 201
        ), f"Failed to create blind shipment: {response.text}"
        data = response.json()
        assert data["is_blind_pickup"] is True
        assert data["estimated_box_count"] == 5
        assert len(data["packages"]) == 0


@pytest.mark.asyncio
async def test_create_blind_pickup_missing_box_count():
    payload1 = generate_dummy_payload()
    payload1["is_blind_pickup"] = True
    payload1["estimated_box_count"] = None
    payload1["packages"] = []

    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{settings.API_V1_STR}/shipments",
            headers=headers,
            json=payload1,
        )
        assert response.status_code == 422
        assert "estimated_box_count must be greater than 0" in response.text

    payload2 = generate_dummy_payload()
    payload2["is_blind_pickup"] = True
    payload2["estimated_box_count"] = 0
    payload2["packages"] = []

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{settings.API_V1_STR}/shipments",
            headers=headers,
            json=payload2,
        )
        assert response.status_code == 422
        assert "estimated_box_count must be greater than 0" in response.text


@pytest.mark.asyncio
async def test_create_manifested_pickup_missing_packages():
    payload = generate_dummy_payload()
    payload["is_blind_pickup"] = False
    payload["packages"] = []

    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{settings.API_V1_STR}/shipments",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 400
        assert (
            "Package details are mandatory for manifested (non-blind) pickups"
            in response.json()["detail"]
        )


@pytest.mark.asyncio
async def test_public_tracking_endpoint_not_found():
    """Verifies unauthenticated GET /api/v1/tracking/{invalid_id} returns 404."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"{settings.API_V1_STR}/tracking/INVALID-TRACKING-123",
            headers={"X-Tenant-Slug": "naviera"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Shipment not found"
