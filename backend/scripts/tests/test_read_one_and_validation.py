
import pytest
import asyncio
from app.core.db import async_engine


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


@pytest.mark.asyncio
async def test_full_flow():
    

    
    from app.core.dependencies import get_current_active_user, get_tenant_from_header
    from app.models.tenants import User, Tenant
    from app.core.db import AsyncSessionLocal, async_engine
    from sqlmodel import select
    import asyncio
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    
    
        
    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:


        # --- 1. Create Shipment ---
        print("\n📦 1. Creating Shipment...")
        create_payload = {
            "order_reference_id": f"VAL-TEST-{str(uuid.uuid4())[:4]}",
            "shipment_type": "FORWARD",
            "service_type": "AIR",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "product_category": "ELECTRONICS",
            "new_pickup_address": {
                "name": "Warehouse Val",
                "phone": "9999999999",
                "address_line1": "Road 1",
                "city": "Delhi",
                "state": "DL",
                "pincode": "110001",
            },
            "new_delivery_address": {
                "name": "Customer Val",
                "phone": "8888888888",
                "address_line1": "Road 2",
                "city": "Mumbai",
                "state": "MH",
                "pincode": "400001",
            },
            "packages": [{"length": 10, "breadth": 10, "height": 10, "weight": 1.0}],
        }
        res = await client.post(
            f"{settings.API_V1_STR}/shipments", json=create_payload, headers=headers
        )
        if res.status_code != 201:
            print(f"❌ Setup Failed: {res.text}")
            assert False, f"Setup failed: {res.text}"

        shipment_id = res.json()["id"]
        print(f"   -> ID: {shipment_id}")

        # --- 2. TEST: Private Detail View (GET /shipments/{id}) ---
        print("\n🔍 2. Testing Private Detail View...")
        res = await client.get(
            f"{settings.API_V1_STR}/shipments/{shipment_id}", headers=headers
        )

        if res.status_code == 200:
            data = res.json()
            print("✅ Success! Retrieved full details.")
            if "payment_details" in data:
                print("   -> Can see sensitive internal data (Payment/Address IDs)")
        else:
            print(f"❌ Failed: {res.status_code} {res.text}")
            assert False, f"Detail view failed: {res.text}"

        # --- 3. TEST: Valid State Transition (DRAFT -> OPEN) ---
        print("\n✅ 3. Testing VALID Status Move (DRAFT -> OPEN)...")
        res = await client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json={"status": "OPEN", "comment": "Opening shipment"},
            headers=headers,
        )
        if res.status_code == 200:
            print("✅ Transition Allowed.")
        else:
            print(f"❌ Failed Valid Move: {res.text}")
            assert False, f"Valid status move failed: {res.text}"

        # --- 4. TEST: Invalid State Transition (OPEN -> COMPLETED) ---
        print("\n🛡️  4. Testing INVALID Status Move (OPEN -> COMPLETED)...")
        print("   (This skips ASSIGNED and IN_TRANSIT, so it should fail)")

        res = await client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json={"status": "COMPLETED", "comment": "Trying to skip steps"},
            headers=headers,
        )

        if res.status_code == 400:
            print(f"✅ Guard Rail Working! Server blocked it: {res.json()['detail']}")
        else:
            print(
                f"❌ Security Failed! Server allowed illegal move. Status: {res.status_code}"
            )
            assert False, f"Security check failed! Server allowed illegal move: {res.status_code}"


if __name__ == "__main__":
    asyncio.run(test_full_flow())
