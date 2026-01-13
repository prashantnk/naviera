import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.tenants import Tenant, User
from app.schemas.v1.pickups import PickupCreate, PickupRead
from app.services.shipment import ShipmentService, get_shipment_service

# --- Setup Logger ---
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/", response_model=PickupRead, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    *,
    payload: PickupCreate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Create a new Shipment.
    
    - **Authentication**: Requires a valid JWT and X-Tenant-Slug header.
    - **Validation**: Checks if "Saved Address IDs" belong to the current tenant.
    - **Transaction**: Creates Addresses (if new), Packages, and Shipment in one go.
    """
    logger.info(f"API Request: Create Shipment for Tenant '{current_tenant.slug}' by User '{current_user.email}'")
    
    logger.debug(f"Payload: order_ref={payload.order_reference_id}, packages={len(payload.packages)}")

    shipment = await shipment_service.create_shipment(
        payload=payload,
        tenant_id=current_tenant.id,
        user_id=current_user.id
    )
    
    logger.info(f"API Success: Created Shipment ID {shipment.id}")
    return shipment