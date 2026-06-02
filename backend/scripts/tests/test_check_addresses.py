import pytest
from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.pickups import Address


@pytest.mark.asyncio
async def test_check_saved_addresses():
    async with AsyncSessionLocal() as session:  # type: ignore
        # Query only "Saved" addresses
        statement = select(Address).where(Address.is_saved)
        result = await session.exec(statement)
        addresses = result.all()

        print(f"\nFound {len(addresses)} Saved Addresses:")
        for addr in addresses:
            print(f" - [{addr.category} / {addr.scope}] {addr.name} (User ID: {addr.user_id})")

        # Assert that addresses query executed and returned a list structure
        assert isinstance(addresses, list)
