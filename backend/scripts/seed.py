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
# Add a placeholder Supabase User ID for our seed user.
OWNER_SUPABASE_ID = "a1b2c3d4-e5f6-7890-1234-567890abcdef"
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

        # Query for the user using the unique combination of supabase_id and tenant_id
        statement = select(User).where(
            User.supabase_user_id == OWNER_SUPABASE_ID, User.tenant_id == tenant.id
        )
        result = await session.exec(statement)
        user = result.first()

        if not user:
            print(f"Creating owner user: {OWNER_EMAIL}")
            user = User(
                email=OWNER_EMAIL,
                supabase_user_id=OWNER_SUPABASE_ID,  # Add the new field
                tenant_id=tenant.id,
                role=UserRole.owner,
                is_active=True,
            )
            session.add(user)
            await session.commit()
        else:
            print(f"Owner user '{OWNER_EMAIL}' already exists. Skipping.")

    print("Seeding finished.")


async def main():
    """Main async function to run the seeder."""
    await seed_data()


def main_wrapper():
    """Synchronous wrapper to run the main async function."""
    asyncio.run(main())


if __name__ == "__main__":
    main_wrapper()
