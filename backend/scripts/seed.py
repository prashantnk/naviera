import asyncio

from app.core.db import AsyncSessionLocal
from app.models.tenants import Tenant, User, UserRole
from sqlmodel import select

# --- Configuration for the Seed Data ---
# We define our first tenant and its owner here.
# Using variables makes it easy to change later.
TENANT_NAME = "Naviera Logistics"
TENANT_SLUG = "naviera"
OWNER_EMAIL = "owner@naviera.com"
# ---


async def seed_data():
    """
    Asynchronous function to seed the database with initial data.
    """
    print("Seeding database with initial data...")

    # AsyncSessionLocal() is the factory we created in db.py
    # We use an 'async with' block to ensure the session is always closed.
    async with AsyncSessionLocal() as session:  # type: ignore
        # Check if the tenant already exists using its unique slug
        statement = select(Tenant).where(Tenant.slug == TENANT_SLUG)
        result = await session.exec(statement)
        tenant = result.first()

        if tenant:
            print(f"Tenant '{TENANT_NAME}' already exists. Skipping.")
        else:
            # If the tenant doesn't exist, create it.
            print(f"Creating tenant: {TENANT_NAME}")
            tenant = Tenant(name=TENANT_NAME, slug=TENANT_SLUG)
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)

        # Now, check if the owner user already exists for this tenant
        statement = select(User).where(
            User.email == OWNER_EMAIL, User.tenant_id == tenant.id
        )
        result = await session.exec(statement)
        user = result.first()

        if user:
            print(f"Owner user '{OWNER_EMAIL}' already exists. Skipping.")
        else:
            # If the user doesn't exist, create it.
            print(f"Creating owner user: {OWNER_EMAIL}")
            user = User(
                email=OWNER_EMAIL,
                tenant_id=tenant.id,
                role=UserRole.owner,
                is_active=True,
            )
            session.add(user)
            await session.commit()

    print("Seeding finished.")


async def main():
    """Main async function to run the seeder."""
    await seed_data()


def main_wrapper():
    """Synchronous wrapper to run the main async function."""
    asyncio.run(main())


if __name__ == "__main__":
    main_wrapper()
