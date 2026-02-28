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
                "toll_free": "1800-000-0000",
                "phones": ["9430650271"],
                "emails": ["pashantnk2001@gmail.com"],
                "address": "Naviera HQ\nCPR Brindavanam, Hyderabad - 500081",
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
                            "images": [
                                "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?q=80&w=2070&auto=format&fit=crop"
                            ],
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
                "toll_free": "1800-309-1130",
                "phones": [
                    "1800-309-1130",
                    "9205-444-895",
                    "9205-444-896",
                    "9205-444-897",
                ],
                "emails": ["contact@logismart.in", "logismartprivatelimited@gmail.com"],
                "whatsapp": "9821008627",
                "address": "632/5, Patel Nagar, Gali No-3\nGurgaon - 122001, Haryana",
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
                    },
                    {
                        "type": "FEATURES",
                        "content": {
                            "badge": "WHY LOGISMART SHIPPING?",
                            "headline": "Complete Logistics & Courier Solutions",
                            "subheadline": "We are an Indian company providing logistics & courier solutions to businesses looking for excellence and innovation. Committed to SERVE.",
                            "features": [
                                {
                                    "title": "Fully IT Enabled Setup",
                                    "description": "Hands-on information for any cargo booked through us. Manage your entire supply chain seamlessly.",
                                    "icon": "monitor",
                                    "bullets": [
                                        "Secured Login & Online Tracking",
                                        "Generate Manifests & Download MIS",
                                        "Order Status & NDR Reports",
                                        "COD Remittance Reports",
                                    ],
                                },
                                {
                                    "title": "E-Commerce Ready",
                                    "description": "Packages tailored for B2B and B2C startups with specialized capabilities.",
                                    "icon": "shopping-bag",
                                    "bullets": [
                                        "Cash on Delivery (COD)",
                                        "Reverse Pickup & Open Delivery",
                                        "Same & Next Day Delivery",
                                    ],
                                },
                                {
                                    "title": "Pan India Presence",
                                    "description": "Distance & time are not a barrier for us. Air, Surface, Train, Cargo, Export, and Import covered extensively.",
                                    "icon": "globe",
                                },
                                {
                                    "title": "Value For Money",
                                    "description": "Our seamless nature integrates directly with client workflows, making us the intelligent choice for prime customer service.",
                                    "icon": "package",
                                    "bullets": [
                                        "Round the clock pickup & delivery",
                                        "Single account multiple locations",
                                        "Sunday/Holiday support",
                                        "Remote location delivery",
                                    ],
                                },
                            ],
                            "clientsHeadline": "Trusted by Leading Brands Across Industries",
                            "clientsSubheadline": "Apparel, Electronics, Automotive, FMCG & Pharma",
                            "clientLogos": [
                                {"name": "Nestle", "color": "#1e40af"},  # Blue
                                {"name": "ITC Limited", "color": "#dc2626"},  # Red
                                {"name": "JOCKEY", "color": "#0f172a"},  # Black
                                {
                                    "name": "WILLS LIFESTYLE",
                                    "color": "#1e293b",
                                },  # Dark Slate
                                {"name": "micromax", "color": "#2563eb"},  # Blue
                                {"name": "MRF", "color": "#b91c1c"},  # Deep Red
                                {"name": "ASHOK LEYLAND", "color": "#0f172a"},  # Black
                                {"name": "Hero", "color": "#ef4444"},  # Red
                                {"name": "Dr.Reddy's", "color": "#1d4ed8"},  # Blue
                                {"name": "NIVEA", "color": "#1e3a8a"},  # Navy
                                {"name": "BRITANNIA", "color": "#15803d"},  # Green
                            ],
                        },
                    },
                ]
            },
            "about_page": {
                "headline": "About Logismart",
                "paragraphs": [
                    "Logismart is one of India's fastest-growing logistics and supply chain companies, offering end-to-end solutions that meet the dynamic needs of modern businesses. Established with a vision to simplify logistics while ensuring speed, safety, and reliability, we have built a strong presence across India and international markets. From express parcel delivery to specialized cargo movement, Logismart has become a trusted partner for enterprises, SMEs, and e-commerce players.",
                    "At Logismart, we go beyond traditional logistics by offering tailor-made services for industries such as pharmaceuticals, fashion, electronics, FMCG, automotive, and more. Our solutions are designed to handle high volumes with accuracy, covering air, train, and surface cargo, along with reverse logistics and warehousing facilities.",
                    "What truly sets Logismart apart is our customer-first approach and commitment to innovation. We believe logistics is not just about moving goods—it is about creating value for clients and enabling their growth.",
                ],
                "offersHeadline": "What We Offer",
                "offers": [
                    {
                        "title": "Retail/Individuals",
                        "description": "A dedicated online courier solution for personal parcel/shipments, with door step pickup and real-time tracking.",
                    },
                    {
                        "title": "B2C",
                        "description": "End to end logistics solutions including express and premium delivery, cross-border cargo/shipping, and warehousing solutions.",
                    },
                    {
                        "title": "B2B",
                        "description": "Reliable bulk shipping and cargo movement with advanced tech and a nationwide logistics network.",
                    },
                    {
                        "title": "E-commerce",
                        "description": "Bulk shipment booking/manifesting within seconds and API integration of e-commerce shipping with real time tracking.",
                    },
                ],
            },
            "services_page": {
                "headline": "Our Services",
                "description": "Logismart is a multi-modal logistics service provider offering an entire range of integrated supply chain management functions.",
                "services": [
                    {
                        "title": "Air Cargo",
                        "icon": "plane",
                        "description": "Daily air freight consolidation, direct air freight and transit air freight. Door to Airport & Airport to Door service available.",
                    },
                    {
                        "title": "Train Cargo",
                        "icon": "train",
                        "description": "Association with all SLR/VPU coaches in all Rajdhani & Express trains. Cost-effective, timely delivery with 24x7 support.",
                    },
                    {
                        "title": "Surface Transportation",
                        "icon": "truck",
                        "description": "We operate a 'Hybrid' model of owned and hired vehicles. Providing Full Truck Load (FTL) and Part Load (LTL) transportation.",
                    },
                    {
                        "title": "Warehousing",
                        "icon": "warehouse",
                        "description": "Customized, state-of-the-art warehousing services. Complete supply chain solutions including inventory management.",
                    },
                    {
                        "title": "E-Commerce Logistics",
                        "icon": "shopping-cart",
                        "description": "Specialized for B2B/B2C startups. Includes Cash on Delivery (COD), Prepaid, Same Day Delivery, Next Day Delivery.",
                    },
                    {
                        "title": "Reverse Logistics",
                        "icon": "refresh-ccw",
                        "description": "Seamless handling of product returns from the end consumer back to the warehouse. Efficient returns reclamation.",
                    },
                ],
                "valueAddHeadline": "Value For Money",
                "valueAddDescription": "We provide specialized support for your critical cargo needs.",
                "valueAdds": [
                    "Round the clock pickup & delivery",
                    "Sunday/Holiday support",
                    "Remote location delivery",
                ],
            },
            "escalation_matrix": [
                {"level": "Level 1 - Support", "email": "contact@logismart.in"},
                {
                    "level": "Level 2 - Sales & Operations",
                    "email": "sales@logismart.in",
                },
                {
                    "level": "Level 3 - Franchise & Management",
                    "email": "franchise@logismart.in",
                },
            ],
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
