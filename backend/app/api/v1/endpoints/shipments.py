import logging
import math
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.tenants import Tenant, User
from app.schemas.v1.common import PaginatedResponse
from app.schemas.v1.pickups import (
    PickupCreate,
    PickupRead,
    PickupUpdate,
    PublicTrackingRead,
    ShipmentActivityRead,
)
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
    logger.info(
        f"API Request: Create Shipment for Tenant '{current_tenant.slug}' by User '{current_user.email}'"
    )

    logger.debug(
        f"Payload: order_ref={payload.order_reference_id}, packages={len(payload.packages)}"
    )

    shipment = await shipment_service.create_shipment(
        payload=payload, tenant=current_tenant, user_id=current_user.id
    )

    logger.info(f"API Success: Created Shipment ID {shipment.id}")
    return shipment


@router.patch("/{shipment_id}", response_model=PickupRead)
async def update_shipment(
    *,
    shipment_id: uuid.UUID,
    payload: PickupUpdate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Update an existing Shipment.

    - **Permissions**: Only Admins/Owners can perform this action.
    - **Features**:
        - Updates fields (Status, Date, etc.)
        - Syncs Packages (Add/Update/Remove)
        - Syncs Documents
        - **Auto-generates Audit Log** (ShipmentActivity)
    """
    logger.info(f"API Request: Update Shipment {shipment_id} by {current_user.email}")

    updated_shipment = await shipment_service.update_shipment(
        shipment_id=shipment_id,
        payload=payload,
        user=current_user,
        tenant_id=current_tenant.id,
    )

    logger.info(f"API Success: Updated Shipment {shipment_id}")
    return updated_shipment


@router.get("/", response_model=PaginatedResponse[PickupRead])
async def list_shipments(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    List Shipments (Paginated).
    - **Admins**: View ALL shipments.
    - **Customers**: View ONLY their created shipments.
    """
    # Unpack the Tuple
    items, total = await shipment_service.list_my_shipments(
        user=current_user, tenant_id=current_tenant.id, page=page, size=size
    )

    # Calculate total pages
    total_pages = math.ceil(total / size) if size > 0 else 0

    return PaginatedResponse(
        items=items, total=total, page=page, size=size, pages=total_pages
    )


@router.get("/{shipment_id}/timeline", response_model=List[ShipmentActivityRead])
async def get_shipment_timeline(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Get Audit Timeline.
    - **Restricted**: Only Admins/Owners can view this full technical history.
    """
    return await shipment_service.get_timeline(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )


@router.get("/tracking/{tracking_id}", response_model=PublicTrackingRead)
async def track_shipment(
    tracking_id: str,
    # Note: NO User Dependency here. This is public.
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Public Tracking Page.
    - **Public**: No authentication required.
    - **Data**: Returns sanitized status and public timeline events only.
    """
    return await shipment_service.track_shipment_public(tracking_id=tracking_id)


@router.get("/{shipment_id}", response_model=PickupRead)
async def get_shipment_details(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Get full details of a specific shipment.
    - **Admins**: Can view any shipment.
    - **Customers**: Can only view their own.
    """
    return await shipment_service.get_shipment_details(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )
