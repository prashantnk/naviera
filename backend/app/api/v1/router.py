from fastapi import APIRouter

from app.api.v1.endpoints import shipments, tenants, users

api_router = APIRouter()
api_router.include_router(tenants.router, prefix="/tenants", tags=["Tenants"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])

api_router.include_router(shipments.router, prefix="/shipments", tags=["Shipments"])
