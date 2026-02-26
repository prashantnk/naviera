import asyncio
from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.tenants import Tenant, User, UserRole

OWNER_SUPABASE_ID = "a1b2c3d4-e5f6-7890-1234-567890abcdef"

# Define our two tenants
TENANTS = [
    {
        "name": "Naviera Logistics",
        "slug": "naviera",
        "email": "admin@naviera.com",
        "settings": {
            "brand": {"primary_color": "#2563eb"}, # BLUE
            "landing_page": {
                "blocks": [
                    {
                        "type": "HERO",
                        "content": {
                            "title": "The Operating System for Modern Logistics",
                            "subtitle": "Manage shipments, multi-tenant billing, and tracking with one API.",
                            "ctaText": "Start Free Trial",
                            "ctaLink": "/login",
                            "badge": "Naviera Platform"
                        }
                    }
                ]
            }
        }
    },
    {
        "name": "Logismart Shipping",
        "slug": "logismart",
        "email": "admin@logismart.com",
        "settings": {
            "brand": {"primary_color": "#dc2626"}, # RED
            "landing_page": {
                "blocks": [
                    {
                        "type": "HERO",
                        "content": {
                            "title": "Fast, Safe & Reliable Delivery Across the World.",
                            "subtitle": "Simplifying delivery through innovation, efficiency, and trust for individuals and enterprises across India.",
                            "ctaText": "Book a Shipment",
                            "ctaLink": "/login",
                            "badge": "Global Logistics Solutions"
                        }
                    }
                ]
            }
        }
    }
]

async def seed_data():
    print("Seeding database with tenants...")

    async with AsyncSessionLocal() as session: # type: ignore
        for t_data in TENANTS:
            # 1. Upsert Tenant
            statement = select(Tenant).where(Tenant.slug == t_data["slug"])
            result = await session.exec(statement)
            tenant = result.first()

            if tenant:
                print(f"Updating existing tenant: {t_data['name']}")
                tenant.settings = t_data["settings"]
                session.add(tenant)
            else:
                print(f"Creating tenant: {t_data['name']}")
                tenant = Tenant(
                    name=t_data["name"], 
                    slug=t_data["slug"],
                    settings=t_data["settings"]
                )
                session.add(tenant)
            
            await session.commit()
            await session.refresh(tenant)

            # 2. Check and Create Admin User
            statement = select(User).where(
                User.supabase_user_id == OWNER_SUPABASE_ID, User.tenant_id == tenant.id
            )
            result = await session.exec(statement)
            user = result.first()

            if not user:
                print(f"Creating owner user: {t_data['email']}")
                user = User(
                    email=t_data["email"],
                    supabase_user_id=OWNER_SUPABASE_ID,
                    tenant_id=tenant.id,
                    role=UserRole.owner,
                    is_active=True,
                )
                session.add(user)
                await session.commit()

    print("Seeding finished.")

def main_wrapper():
    asyncio.run(seed_data())

if __name__ == "__main__":
    main_wrapper()