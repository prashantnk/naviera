"""
Reverse bookings (B2C DTO vs B2B MVP guard) and RTO pricing recalculation integration tests.
"""

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

HEADERS = {"X-Tenant-Slug": "logismart-test"}


@pytest.mark.asyncio
async def test_create_b2b_reverse_shipment_pricing():
    """
    Verify B2B reverse LRs are blocked in MVP (400) while B2C reverse (DTO) shipments
    succeed (201) and return chargeable_weight and return pricing breakdown.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        b2b_payload = {
            "order_reference_id": f"REV-B2B-{str(uuid.uuid4())[:4]}",
            "shipment_type": "REVERSE",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "product_category": "ELECTRONICS",
            "reason_for_return": "Customer return - defective item",
            "is_carriers_risk": True,
            "new_pickup_address": {
                "name": "Customer Location",
                "phone": "9999999999",
                "address_line1": "Road 10",
                "city": "Gurugram",
                "state": "HR",
                "pincode": "122001",
            },
            "new_delivery_address": {
                "name": "B2B Hub",
                "phone": "8888888888",
                "address_line1": "Warehouse A",
                "city": "Mumbai",
                "state": "MH",
                "pincode": "400001",
            },
            "packages": [
                {
                    "length": 30.0,
                    "breadth": 20.0,
                    "height": 10.0,
                    "weight": 2.0,
                    "box_count": 1,
                    "description": "Returned Electronics",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "PREPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_total_value": 1000.0,
            },
        }
        blocked = await client.post(
            f"{settings.API_V1_STR}/shipments", json=b2b_payload, headers=HEADERS
        )
        assert blocked.status_code == 400, blocked.text
        assert "B2B reverse" in blocked.json()["detail"]

        b2c_payload = {
            **b2b_payload,
            "order_reference_id": f"REV-B2C-{str(uuid.uuid4())[:4]}",
            "is_carriers_risk": False,
        }
        res = await client.post(
            f"{settings.API_V1_STR}/shipments", json=b2c_payload, headers=HEADERS
        )
        assert res.status_code == 201, res.text
        data = res.json()

        pay = data["payment_details"]
        assert pay["base_freight"] > 0
        assert "chargeable_weight" in pay
        assert pay["chargeable_weight"] == 2.0


@pytest.mark.asyncio
async def test_rto_status_transition_recalculates_pricing():
    """
    Verify transitioning IN_TRANSIT -> RTO_INITIATED bills the RTO leg via RepricingService.
    """
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
                "name": "Warehouse A",
                "phone": "9999999999",
                "address_line1": "Road 1",
                "city": "Gurugram",
                "state": "HR",
                "pincode": "122001",
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
                    "length": 30.0,
                    "breadth": 20.0,
                    "height": 10.0,
                    "weight": 2.0,
                    "box_count": 1,
                    "description": "Box 1",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "PREPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_total_value": 1000.0,
            },
        }

        res = await client.post(
            f"{settings.API_V1_STR}/shipments", json=payload, headers=HEADERS
        )
        assert res.status_code == 201, res.text
        shipment = res.json()
        shipment_id = shipment["id"]
        initial_total = shipment["payment_details"]["total_logistics_cost"]

        # Verify initial pricing has NO rto_surcharge
        assert shipment["payment_details"]["pricing_breakdown"]["rto_surcharge"] == 0.0

        # OPEN -> ASSIGNED -> IN_TRANSIT
        await client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json={"status": "ASSIGNED", "comment": "Driver assigned"},
            headers=HEADERS,
        )
        await client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json={"status": "IN_TRANSIT", "comment": "Shipped"},
            headers=HEADERS,
        )

        # Transition IN_TRANSIT -> RTO_INITIATED
        res = await client.patch(
            f"{settings.API_V1_STR}/shipments/{shipment_id}",
            json={
                "status": "RTO_INITIATED",
                "comment": "Delivery refused by customer, initiating return to origin",
            },
            headers=HEADERS,
        )
        assert res.status_code == 200, res.text
        updated_shipment = res.json()

        pay = updated_shipment["payment_details"]
        breakdown = pay["pricing_breakdown"]
        assert breakdown["rto_surcharge"] > 0.0
        assert pay["total_logistics_cost"] > initial_total


@pytest.mark.asyncio
async def test_create_reverse_shipment_with_qc():
    """
    Verify B2C reverse (DTO) shipment creation with qc_required and qc_notes.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "order_reference_id": f"REV-QC-{str(uuid.uuid4())[:4]}",
            "shipment_type": "REVERSE",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "06:00 - 10:00",
            "product_category": "ELECTRONICS",
            "reason_for_return": "Customer return - defective item",
            "is_carriers_risk": False,
            "qc_required": True,
            "qc_notes": "Check for scratches and original charger",
            "new_pickup_address": {
                "name": "Customer Location",
                "phone": "9999999999",
                "address_line1": "Road 10",
                "city": "Mumbai",
                "state": "MH",
                "pincode": "400001",
            },
            "new_delivery_address": {
                "name": "B2C Hub",
                "phone": "8888888888",
                "address_line1": "Warehouse A",
                "city": "Delhi",
                "state": "DL",
                "pincode": "110001",
            },
            "packages": [
                {
                    "length": 30.0,
                    "breadth": 20.0,
                    "height": 10.0,
                    "weight": 2.0,
                    "box_count": 1,
                    "description": "Returned Electronics",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "PREPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_total_value": 1000.0,
            },
        }

        res = await client.post(
            f"{settings.API_V1_STR}/shipments", json=payload, headers=HEADERS
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["qc_required"] is True
        assert data["qc_notes"] == "Check for scratches and original charger"
