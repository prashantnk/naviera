import uuid
import asyncio
from datetime import date
from app.core.config import settings
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.tenants import User, Tenant
from app.core.db import AsyncSessionLocal, async_engine
from sqlmodel import select
import pytest





@pytest.mark.asyncio
async def test_edit_flow():
    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create
        create_payload = {
            "order_reference_id": f"TEST-{str(uuid.uuid4())[:4]}",
            "shipment_type": "FORWARD",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "product_category": "ELECTRONICS",
            "new_pickup_address": {
                "name": "Warehouse A", "phone": "9999999999", "address_line1": "Road 1", "city": "Delhi", "state": "DL", "pincode": "110001"
            },
            "new_delivery_address": {
                "name": "Customer B", "phone": "8888888888", "address_line1": "Road 2", "city": "Mumbai", "state": "MH", "pincode": "400001"
            },
            "packages": [{"length": 10, "breadth": 10, "height": 10, "weight": 1.0, "description": "Box 1"}],
            "payment_details": {
                "invoice_numbers": ["INV-001", "INV-002"],
                "eway_bill_numbers": ["EWAY-999"]
            }
        }
        print('Before post'); res = await client.post(f"{settings.API_V1_STR}/shipments", json=create_payload, headers=headers)
        assert res.status_code == 201, res.text
        shipment = res.json()
        shipment_id = shipment["id"]
        pkg_id = shipment["packages"][0]["id"]

        # Update
        update_payload = {
            "status": "OPEN", "comment": "Test edit flow",
            "packages": [
                {"id": pkg_id, "length": 10, "breadth": 10, "height": 10, "weight": 2.5, "description": "Box 1 (Updated)"},
                {"length": 20, "breadth": 20, "height": 20, "weight": 5.0, "description": "Box 2 (New)"}
            ],
            "payment_details": {
                "invoice_numbers": ["INV-001", "INV-002"],
                "eway_bill_numbers": ["EWAY-999"]
            }
        }
        print('Before patch'); res = await client.patch(f"{settings.API_V1_STR}/shipments/{shipment_id}", json=update_payload, headers=headers)
        assert res.status_code == 200, res.text; print('After patch')
