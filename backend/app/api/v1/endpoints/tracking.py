from fastapi import APIRouter, Depends

from app.core.dependencies import get_tenant_from_header
from app.models.tenants import Tenant
from app.schemas.v1.pickups import PublicTrackingRead
from app.services.shipment import ShipmentService, get_shipment_service

router = APIRouter()

@router.get("/{identifier}", response_model=PublicTrackingRead)
async def track_shipment(
    identifier: str,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Public Tracking Page.
    - **Public**: No authentication required.
    - **Data**: Returns sanitized status and public timeline events only.
    """
    return await shipment_service.track_shipment_public(
        identifier=identifier, tenant_id=current_tenant.id
    )
