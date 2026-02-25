import asyncio
from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.tenants import Tenant, User, UserRole

TENANT_NAME = "Naviera Logistics"
TENANT_SLUG = "naviera"
OWNER_EMAIL = "owner@naviera.com"
OWNER_SUPABASE_ID = "a1b2c3d4-e5f6-7890-1234-567890abcdef"

async def seed_data():
    print("Seeding database with initial data...")

    async with AsyncSessionLocal() as session: # type: ignore
        # --- The UI Configuration Data ---
        marketing_config = {
            "brand": {"primary_color": "#2563eb"},
            "landing_page": {
                "blocks": [
                    {
                        "type": "HERO",
                        "content": {
                            "title": "Logistics for the Future (From DB)",
                            "subtitle": "This content is being served live from your FastAPI Backend + Supabase Postgres.",
                            "ctaText": "Start Shipping",
                            "ctaLink": "/login",
                            "badge": "Live Data 🚀"
                        }
                    }
                ]
            }
        }
        
        # 1. Check if the tenant exists
        statement = select(Tenant).where(Tenant.slug == TENANT_SLUG)
        result = await session.exec(statement)
        tenant = result.first()

        if tenant:
            print(f"Tenant '{TENANT_NAME}' exists. Updating settings...")
            tenant.settings = marketing_config # <--- Force update the settings
            session.add(tenant)
            await session.commit()
        else:
            print(f"Creating tenant: {TENANT_NAME}")
            tenant = Tenant(
                name=TENANT_NAME, 
                slug=TENANT_SLUG,
                settings=marketing_config
            )
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)

        # 2. Check and Create User
        statement = select(User).where(
            User.supabase_user_id == OWNER_SUPABASE_ID, User.tenant_id == tenant.id
        )
        result = await session.exec(statement)
        user = result.first()

        if not user:
            print(f"Creating owner user: {OWNER_EMAIL}")
            user = User(
                email=OWNER_EMAIL,
                supabase_user_id=OWNER_SUPABASE_ID,
                tenant_id=tenant.id,
                role=UserRole.owner,
                is_active=True,
            )
            session.add(user)
            await session.commit()
        else:
            print(f"Owner user '{OWNER_EMAIL}' already exists. Skipping.")

    print("Seeding finished.")

def main_wrapper():
    asyncio.run(seed_data())

if __name__ == "__main__":
    main_wrapper()