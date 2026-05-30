import uuid
from datetime import date

import httpx

from app.core.config import settings

# --- Config ---
TEST_USER_EMAIL = "naviera_test_user@naviera.com"
TEST_USER_PASSWORD = "NavieraTestUser"
TENANT_SLUG = "naviera"
API_BASE_URL = "http://localhost:8000"

# Import Supabase Client
from supabase import Client, create_client


def get_auth_token():
    print("🔐 Authenticating...")
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    res = supabase.auth.sign_in_with_password(
        {"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
    )
    return res.session.access_token  # type: ignore


def test_edit_flow():
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-Slug": TENANT_SLUG}

    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        # --- Step 1: Create Shipment ---
        print("\n📦 1. Creating Initial Shipment...")
        create_payload = {
            "order_reference_id": f"TEST-{str(uuid.uuid4())[:4]}",
            "shipment_type": "FORWARD",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "new_pickup_address": {
                "name": "Warehouse A",
                "phone": "9999999999",
                "address_line1": "Road 1",
                "city": "Delhi",
                "state": "DL",
                "pincode": "110001",
            },
            "new_delivery_address": {
                "name": "Customer B",
                "phone": "8888888888",
                "address_line1": "Road 2",
                "city": "Mumbai",
                "state": "MH",
                "pincode": "400001",
            },
            "packages": [
                {
                    "length": 10,
                    "breadth": 10,
                    "height": 10,
                    "weight": 1.0,
                    "description": "Box 1",
                }
            ],
        }
        res = client.post(
            f"{settings.API_V1_STR}/shipments", json=create_payload, headers=headers
        )
        if res.status_code != 201:
            print(f"❌ Creation Failed: {res.text}")
            return

        shipment = res.json()
        shipment_id = shipment["id"]
        pkg_id = shipment["packages"][0]["id"]
        print(f"✅ Created Shipment {shipment_id}")

        # --- Step 2: Edit Shipment (The Test) ---
        print("\n✏️  2. Sending Update Request...")
        # Scenario:
        # - Change Status to OPEN
        # - Change Weight of Box 1 (1.0 -> 2.5)
        # - Add Box 2
        update_payload = {
            "status": "OPEN",
            "comment": "Driver arrived at warehouse",
            "packages": [
                # Update existing box (Must send ID)
                {
                    "id": pkg_id,
                    "length": 10,
                    "breadth": 10,
                    "height": 10,
                    "weight": 2.5,  # <--- CHANGED
                    "description": "Box 1 (Updated)",
                },
                # Add new box (No ID)
                {
                    "length": 20,
                    "breadth": 20,
                    "height": 20,
                    "weight": 5.0,
                    "description": "Box 2 (New)",
                },
            ],
        }

        res = client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json=update_payload,
            headers=headers,
        )

        if res.status_code == 200:
            updated = res.json()
            print("\n✅ Update Successful!")
            print(f"New Status: {updated['status']}")
            print(f"Package Count: {len(updated['packages'])} (Expected 2)")

            # Note: To see the actual Activity Log, we would need to inspect the DB
            # or build the GET /timeline endpoint next.
            print(
                "\n(Check your database 'shipment_activities' table to see the generated JSON diff!)"
            )
        else:
            print(f"❌ Update Failed: {res.status_code}")
            print(res.text)


if __name__ == "__main__":
    test_edit_flow()
