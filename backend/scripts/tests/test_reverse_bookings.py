# backend/scripts/tests/test_reverse_bookings.py
import uuid
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings

@pytest.mark.asyncio
async def test_create_b2b_reverse_shipment_pricing():
    """
    Verify B2B reverse shipment creation and check if chargeable_weight is returned.
    """
    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "order_reference_id": f"REV-{str(uuid.uuid4())[:4]}",
            "shipment_type": "REVERSE",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "product_category": "ELECTRONICS",
            "reason_for_return": "Customer return - defective item",
            "is_carriers_risk": True,
            "new_pickup_address": {
                "name": "Customer Location", "phone": "9999999999", "address_line1": "Road 10", "city": "Mumbai", "state": "MH", "pincode": "400001"
            },
            "new_delivery_address": {
                "name": "B2B Hub", "phone": "8888888888", "address_line1": "Warehouse A", "city": "Delhi", "state": "DL", "pincode": "110001"
            },
            "packages": [{"length": 30.0, "breadth": 20.0, "height": 10.0, "weight": 2.0, "box_count": 1, "description": "Returned Electronics"}],
            "payment_details": {
                "freight_payment_mode": "PREPAID", "is_cod": False, "cod_amount": 0.0, "shipment_total_value": 1000.0
            }
        }
        
        res = await client.post(f"{settings.API_V1_STR}/shipments", json=payload, headers=headers)
        assert res.status_code == 201, res.text
        data = res.json()
        
        pay = data["payment_details"]
        print("\n--- Created Shipment Payment Details Response ---")
        print(pay)
        
        # Verify that base freight and surcharges are calculated correctly
        assert pay["base_freight"] == 500.0
        breakdown = pay["pricing_breakdown"]
        assert breakdown["rto_surcharge"] == 250.0
        assert breakdown["docket_charge"] == 50.0
        assert breakdown["fov_charge"] == 50.0
        
        # Bug 1 Verification: Check if chargeable_weight is missing from the response schema
        if "chargeable_weight" not in pay:
            print("\n❌ BUG CONFIRMED: 'chargeable_weight' is missing from the API response schema PaymentDetailsRead!")
            assert False, "chargeable_weight is missing from the API response schema"
        
        assert pay["chargeable_weight"] == 10.0


@pytest.mark.asyncio
async def test_rto_status_transition_recalculates_pricing():
    """
    Verify if transitioning to RTO_INITIATED status triggers pricing recalculation.
    """
    headers = {"X-Tenant-Slug": "naviera"}
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
                "name": "Warehouse A", "phone": "9999999999", "address_line1": "Road 1", "city": "Delhi", "state": "DL", "pincode": "110001"
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
        
        # Verify initial pricing has NO rto_surcharge
        assert shipment["payment_details"]["pricing_breakdown"]["rto_surcharge"] == 0.0
        
        # DRAFT -> OPEN -> ASSIGNED -> IN_TRANSIT
        res = await client.patch(f"{settings.API_V1_STR}/shipments/{shipment_id}", json={"status": "OPEN", "comment": "Ready for pickup"}, headers=headers)
        res = await client.patch(f"{settings.API_V1_STR}/shipments/{shipment_id}", json={"status": "ASSIGNED", "comment": "Driver assigned"}, headers=headers)
        res = await client.patch(f"{settings.API_V1_STR}/shipments/{shipment_id}", json={"status": "IN_TRANSIT", "comment": "Shipped"}, headers=headers)
        
        # Transition IN_TRANSIT -> RTO_INITIATED
        res = await client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json={"status": "RTO_INITIATED", "comment": "Delivery refused by customer, initiating return to origin"},
            headers=headers
        )
        assert res.status_code == 200, res.text
        updated_shipment = res.json()
        
        pay = updated_shipment["payment_details"]
        breakdown = pay["pricing_breakdown"]
        
        print("\n--- Updated Shipment Payment Details after RTO_INITIATED ---")
        print(pay)
        
        # Bug 2 Verification: Check if rto_surcharge is still 0.0 (meaning recalculation did not run)
        if breakdown["rto_surcharge"] == 0.0:
            print("\n❌ BUG CONFIRMED: Transition to RTO_INITIATED did not trigger pricing recalculation!")
            print(f"Surcharge remains: {breakdown['rto_surcharge']} (Expected: 250.0)")
            assert False, "Transition to RTO_INITIATED did not trigger pricing recalculation"
        
        assert breakdown["rto_surcharge"] == 250.0

@pytest.mark.asyncio
async def test_create_reverse_shipment_with_qc():
    """
    Verify reverse shipment creation with qc_required and qc_notes.
    """
    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "order_reference_id": f"REV-QC-{str(uuid.uuid4())[:4]}",
            "shipment_type": "REVERSE",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "product_category": "ELECTRONICS",
            "reason_for_return": "Customer return - defective item",
            "is_carriers_risk": True,
            "qc_required": True,
            "qc_notes": "Check for scratches and original charger",
            "new_pickup_address": {
                "name": "Customer Location", "phone": "9999999999", "address_line1": "Road 10", "city": "Mumbai", "state": "MH", "pincode": "400001"
            },
            "new_delivery_address": {
                "name": "B2B Hub", "phone": "8888888888", "address_line1": "Warehouse A", "city": "Delhi", "state": "DL", "pincode": "110001"
            },
            "packages": [{"length": 30.0, "breadth": 20.0, "height": 10.0, "weight": 2.0, "box_count": 1, "description": "Returned Electronics"}],
            "payment_details": {
                "freight_payment_mode": "PREPAID", "is_cod": False, "cod_amount": 0.0, "shipment_total_value": 1000.0
            }
        }
        
        res = await client.post(f"{settings.API_V1_STR}/shipments", json=payload, headers=headers)
        assert res.status_code == 201, res.text
        data = res.json()
        
        assert data["qc_required"] is True
        assert data["qc_notes"] == "Check for scratches and original charger"
