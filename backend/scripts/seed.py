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
            "brand": {"primary_color": "#2563eb", "logo_url": None},  # BLUE
            "contact": {
                "phone": "1800-000-0000",
                "email": "hello@naviera.com",
                "whatsapp": "9999999999",
            },
            "landing_page": {
                "blocks": [
                    {
                        "type": "HERO",
                        "content": {
                            "title": "The Operating System for Modern Logistics",
                            "subtitle": "Manage shipments, multi-tenant billing, and tracking with one API.",
                            "ctaText": "Start Free Trial",
                            "ctaLink": "/login",
                            "badge": "Naviera Platform",
                            "trustPartners": ["OceanWay", "AeroSwift", "GroundForce"],
                        },
                    }
                ]
            },
        },
    },
    {
        "name": "Logismart",
        "slug": "logismart",
        "email": "admin@logismart.com",
        "settings": {
            "brand": {
                "primary_color": "#dc2626",
                "logo_url": "/logismart-logo.png",
            },  # RED
            "contact": {
                "phones": [
                    "1800-309-1130",
                    "9205-444-895",
                    "9205-444-896",
                    "9205-444-897",
                ],
                "emails": ["contact@logismart.in", "logismartprivatelimited@gmail.com"],
                "whatsapp": "9821008627",
                "socials": {
                    "facebook": "https://www.facebook.com/logismart.in",
                    "instagram": "https://www.instagram.com/logismartin?fbclid=IwY2xjawNnS0BleHRuA2FlbQIxMABicmlkETFaM1ZmWXRLMTBYaE9oQWdVAR4VQBG8JStxs5Uj666A-tKb8fPNJJ3gadBluDX9ecP_wvpR7K8Rj5oQWHw-DQ_aem_UfWjoOXqRqub78fN-Myjgg",
                    "youtube": "https://www.youtube.com/@logismart",
                    "linkedin": "https://www.linkedin.com/company/logismart-private-limited/about/",
                },
            },
            "landing_page": {
                "blocks": [
                    {
                        "type": "HERO",
                        "content": {
                            "title": "International & Domestic Courier & Cargo Services",
                            "subtitle": "Air, Cargo, Train & Transport. Fast, safe, and reliable delivery across the world.",
                            "ctaText": "Book Your Shipment",
                            "ctaLink": "/shipments/new",
                            "badge": "Logismart Pvt. Ltd.",
                            "trustPartners": [
                                "DHL",
                                "FedEx",
                                "DTDC",
                                "Blue Dart",
                                "UPS",
                            ],
                        },
                    }
                ]
            },
        },
    },
]


async def seed_data():
    print("Seeding database with tenants...")

    async with AsyncSessionLocal() as session:  # type: ignore
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
                    settings=t_data["settings"],
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
