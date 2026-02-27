# backend/app/api/v1/router.py
from fastapi import APIRouter

from app.api.v1.endpoints import shipments, tenants, users, addresses

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(tenants.router, prefix="/tenants", tags=["Tenants"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(shipments.router, prefix="/shipments", tags=["Shipments"])
api_router.include_router(addresses.router, prefix="/addresses", tags=["Addresses"])