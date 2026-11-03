from fastapi import APIRouter

from app.api.v1.endpoints import (
    addresses,
    appointments,
    dashboard,
    delhivery_modules,
    exceptions,
    internal,
    manifests,
    pricing,
    pricing_prime,
    shipments,
    tenants,
    tracking,
    users,
    wallet,
)

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(tenants.router, prefix="/tenants", tags=["Tenants"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(shipments.router, prefix="/shipments", tags=["Shipments"])
api_router.include_router(pricing.quotes_router, prefix="/quotes", tags=["Quotes"])
api_router.include_router(pricing.pricing_router, prefix="/pricing", tags=["Pricing"])
api_router.include_router(pricing_prime.router, prefix="/pricing", tags=["Prime Rates"])
api_router.include_router(addresses.router, prefix="/addresses", tags=["Addresses"])
api_router.include_router(manifests.router, prefix="/manifests", tags=["Manifests"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(exceptions.router, prefix="/exceptions", tags=["Exceptions"])
api_router.include_router(tracking.router, prefix="/shipments/tracking", tags=["Tracking"])
api_router.include_router(tracking.router, prefix="/tracking", tags=["Tracking"])
api_router.include_router(wallet.router, prefix="/wallet", tags=["Wallet"])
api_router.include_router(
    delhivery_modules.remittances_router, prefix="/remittances", tags=["Remittances"]
)
api_router.include_router(
    delhivery_modules.invoices_router, prefix="/invoices", tags=["Invoices"]
)
api_router.include_router(
    delhivery_modules.support_tickets_router,
    prefix="/support-tickets",
    tags=["Support Tickets"],
)
api_router.include_router(
    delhivery_modules.disputes_router, prefix="/disputes", tags=["Disputes"]
)
api_router.include_router(appointments.router, prefix="/appointments", tags=["Appointments"])
api_router.include_router(
    internal.router,
    prefix="/internal",
    tags=["Internal"],
    include_in_schema=False,
)
