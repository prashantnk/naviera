import uuid
from datetime import date

import httpx
from supabase import Client, create_client

from app.core.config import settings

# --- Config ---
TEST_USER_EMAIL = "naviera_test_user@naviera.com"
TEST_USER_PASSWORD = "NavieraTestUser"
TENANT_SLUG = "naviera"
API_BASE_URL = "http://localhost:8000"


def get_auth_token():
    print(f"🔐 Authenticating as {TEST_USER_EMAIL}...")
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    res = supabase.auth.sign_in_with_password(
        {"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
    )
    return res.session.access_token  # type: ignore


def test_read_flow():
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-Slug": TENANT_SLUG}

    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:

        # --- 1. Setup: Create a Shipment ---
        print("\n📦 1. Creating a fresh shipment for testing...")
        create_payload = {
            "order_reference_id": f"READ-TEST-{str(uuid.uuid4())[:4]}",
            "shipment_type": "FORWARD",
            "service_type": "EXPRESS",
            "requested_pickup_date": str(date.today()),
            "new_pickup_address": {
                "name": "Warehouse Read",
                "phone": "9999999999",
                "address_line1": "Road 1",
                "city": "Delhi",
                "state": "DL",
                "pincode": "110001",
            },
            "new_delivery_address": {
                "name": "Customer Read",
                "phone": "8888888888",
                "address_line1": "Road 2",
                "city": "Mumbai",
                "state": "MH",
                "pincode": "400001",
            },
            "packages": [{"length": 10, "breadth": 10, "height": 10, "weight": 1.0}],
        }
        res = client.post(
            f"{settings.API_V1_STR}/shipments/", json=create_payload, headers=headers
        )
        if res.status_code != 201:
            print(f"❌ Setup Failed: {res.text}")
            return

        shipment = res.json()
        shipment_id = shipment["id"]
        tracking_id = shipment["tracking_id"]
        print(f"   -> Created Shipment: {shipment_id}")
        print(f"   -> Tracking ID: {tracking_id}")

        # --- 2. Setup: Add some History (Update it) ---
        print("\n✏️  2. Updating shipment to generate history...")
        update_payload = {
            "status": "OPEN",
            "comment": "Driver assigned for pickup",
            "is_public": True,  # Make this visible to public!
        }
        client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json=update_payload,
            headers=headers,
        )
        print("   -> Status changed to OPEN (Public Event)")

        # --- 3. TEST: Admin Timeline (Restricted) ---
        print("\n🕵️  3. Testing Admin Timeline (GET /shipments/{id}/timeline)...")
        res = client.get(
            f"{settings.API_V1_STR}/shipments/{shipment_id}/timeline", headers=headers
        )

        if res.status_code == 200:
            timeline = res.json()
            print("✅ Admin Timeline Success!")
            print(f"   Count: {len(timeline)} events")
            print(
                f"   Latest Event Diff: {timeline[0].get('diff')}"
            )  # Should show the diff
        else:
            print(f"❌ Admin Timeline Failed: {res.status_code} {res.text}")

        # --- 4. TEST: Public Tracking (Unrestricted) ---
        print(
            f"\n🌍 4. Testing Public Tracking (GET /shipments/tracking/{tracking_id})..."
        )
        # Note: We do NOT send auth headers here to prove it's public
        public_headers = {"X-Tenant-Slug": TENANT_SLUG}
        res = client.get(
            f"{settings.API_V1_STR}/shipments/tracking/{tracking_id}",
            headers=public_headers,
        )

        if res.status_code == 200:
            track_data = res.json()
            print("✅ Public Tracking Success!")
            print(f"   Status: {track_data['status']}")
            print(f"   Timeline Events: {len(track_data['timeline'])}")

            # Validation: Public view should NOT have 'diff' or 'user_id'
            if "diff" not in track_data["timeline"][0]:
                print("   🔒 Security Check Passed: Internal data is hidden.")
            else:
                print("   ⚠️ SECURITY WARNING: Diff leaked to public!")
        else:
            print(f"❌ Public Tracking Failed: {res.status_code} {res.text}")

        # --- 5. TEST: List Shipments ---
        print("\n📋 5. Testing List Shipments (GET /shipments/)...")
        res = client.get(f"{settings.API_V1_STR}/shipments/", headers=headers)
        if res.status_code == 200:
            list_data = res.json()
            print(f"✅ List Success! Found {len(list_data)} shipments.")
        else:
            print(f"❌ List Failed: {res.status_code}")


if __name__ == "__main__":
    test_read_flow()
