import json
import uuid
from datetime import date, timedelta

import httpx
from supabase import Client, create_client

# Import settings to get URLs and Credentials
from app.core.config import settings

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
    print(f"🔐 Authenticating as '{TEST_USER_EMAIL}'...")
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
    # Random Order ID to avoid Unique Constraint errors on re-runs
    random_id = str(uuid.uuid4())[:8].upper()

    return {
        "order_reference_id": f"ORD-{random_id}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today() + timedelta(days=1)),  # Tomorrow
        "pickup_time_slot": "06:00 - 10:00",
        "product_category": "ELECTRONICS",
        # --- SCENARIO: Creating NEW Addresses (Snapshotting) ---
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
        # --- Packages ---
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
        # --- Payment ---
        "payment_details": {
            "amount": 1500.00,
            "payment_mode": "PREPAID",
            "declared_value": 50000.00,
            "tax_amount": 270.00,
        },
        # --- Documents (Optional) ---
        "documents": [
            {
                "document_type": "GST_INVOICE",
                "file_url": "https://s3.aws.com/naviera/inv-123.pdf",
                "file_name": "invoice.pdf",
            }
        ],
    }


def test_shipment_flow():
    jwt = get_auth_token()
    payload = generate_dummy_payload()

    print("\n📦 Sending Shipment Creation Request...")

    headers = {"Authorization": f"Bearer {jwt}", "X-Tenant-Slug": TENANT_SLUG}

    # We use a 30s timeout because database creation might take a moment
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{API_BASE_URL}{settings.API_V1_STR}/shipments",
            headers=headers,
            json=payload,
        )

        assert response.status_code == 201, f"Failed to create shipment: {response.text}"
        
        data = response.json()
        print("\n✅ SHIPMENT CREATED SUCCESSFULLY!")
        print(f"🆔 Shipment ID: {data['id']}")
        print(f"📍 Status: {data['status']}")
        print(f"🚛 Pickup Address ID: {data['pickup_address']['id']}")
        print(f"📦 Package Count: {len(data['packages'])}")
        print(json.dumps(data, indent=2))

        # Assertions
        assert data["id"] is not None
        assert data["status"] == "DRAFT"
        assert data["pickup_address"]["id"] is not None
        assert len(data["packages"]) == 2


if __name__ == "__main__":
    for _ in range(1):
        test_shipment_flow()

