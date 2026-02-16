import asyncio

from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.pickups import Address


async def check_saved_addresses():
    async with AsyncSessionLocal() as session:  # type: ignore
        # Query only "Saved" addresses
        statement = select(Address).where(Address.is_saved == True)
        result = await session.exec(statement)
        addresses = result.all()

        print(f"\nFound {len(addresses)} Saved Addresses:")
        for addr in addresses:
            print(f" - [{addr.address_type}] {addr.name} (User ID: {addr.user_id})")


if __name__ == "__main__":
    asyncio.run(check_saved_addresses())
