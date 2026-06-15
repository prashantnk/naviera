import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings

@pytest.mark.asyncio
async def test_check_saved_addresses():
    headers = {"X-Tenant-Slug": "naviera"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create an address
        payload = {
            "name": "Test Address",
            "phone": "9999999999",
            "address_line1": "123 Test St",
            "city": "Test City",
            "state": "TS",
            "pincode": "123456",
            "country": "IN",
            "category": "HOME"
        }
        res = await client.post(f"{settings.API_V1_STR}/addresses", json=payload, headers=headers)
        assert res.status_code == 200, res.text
        addr_id = res.json()["id"]
        
        # List addresses
        res = await client.get(f"{settings.API_V1_STR}/addresses", headers=headers)
        assert res.status_code == 200
        addresses = res.json()
        assert any(a["id"] == addr_id for a in addresses)

        # Update address
        update_payload = {"city": "Updated City"}
        res = await client.patch(f"{settings.API_V1_STR}/addresses/{addr_id}", json=update_payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["city"] == "Updated City"

        # Delete address
        res = await client.delete(f"{settings.API_V1_STR}/addresses/{addr_id}", headers=headers)
        assert res.status_code == 200

        # Verify deletion
        res = await client.get(f"{settings.API_V1_STR}/addresses", headers=headers)
        assert not any(a["id"] == addr_id for a in res.json())
