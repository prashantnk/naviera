import asyncio

from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.tenants import Tenant, User, UserRole

OWNER_SUPABASE_ID = "a1b2c3d4-e5f6-7890-1234-567890abcdef"

TENANTS = [
    {
        "name": "Naviera",
        "slug": "naviera",
        "email": "pashantnk2001@gmail.com",
        "settings": {
            "brand": {
                "primary_color": "#2563eb",
                "secondary_color": "#1e40af",  # Dark Blue
                "logo_url": None,
            },
            "announcement_bar": {"is_active": False, "text": ""},  # Hidden for Naviera
            "contact": {
                "phones": ["9430650271"],
                "emails": ["pashantnk2001@gmail.com"],
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
                            "layoutVariant": "saas",
                            "images": ["https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?q=80&w=2070&auto=format&fit=crop"],
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
                "primary_color": "#dc2626",  # Logismart Red
                "secondary_color": "#003366",  # Logismart Navy
                "logo_url": "/logismart-logo.png",
            },
            "announcement_bar": {
                "is_active": True,  # Visible for Logismart
                "text": "International Courier & Logistics Solutions Across World - Fast, Safe & Delivery on Time",
            },
            "contact": {
                "phones": [
                    "1800-309-1130",
                    "9205-444-895",
                    "9205-444-896",
                    "9205-444-897",
                ],
                "emails": ["contact@logismart.in", "logismartprivatelimited@gmail.com"],
                "whatsapp": "9821008627",
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
                            "layoutVariant": "logistics_bento",
                            "images": [
                                "https://images.unsplash.com/photo-1542296332-2e4473faf563?q=80&w=2070&auto=format&fit=crop",
                                "https://images.unsplash.com/photo-1601584115197-04ecc0da31d7?q=80&w=2070&auto=format&fit=crop",
                                "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?q=80&w=2070&auto=format&fit=crop",
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
