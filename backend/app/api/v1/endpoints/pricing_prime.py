"""
Staff API for the Logismart Prime rate table (API_CONTRACT.md §7), mounted at `/pricing`.

Thin controller: dependency injection + HTTP shapes only; access rules and import logic
live in `PrimeAdminService`, SQL in `PrimeRatesRepository`.

Spring Boot Equivalent: '@RestController @RequestMapping("/api/v1/pricing")'.
"""

import uuid
from typing import List

from fastapi import APIRouter, Body, Depends, Query, Response

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.tenants import Tenant, User
from app.schemas.v1.prime import (
    PrimeImportReport,
    PrimeLanePatch,
    PrimeLaneRead,
    PrimeZoneRead,
)
from app.services.prime_admin import PrimeAdminService, get_prime_admin_service

CSV_MEDIA_TYPE = "text/csv"
EXPORT_FILENAME = "prime_lanes.csv"
TEMPLATE_FILENAME = "prime_lanes_template.csv"

router = APIRouter()


@router.get("/prime-zones", response_model=List[PrimeZoneRead])
async def list_prime_zones(
    *,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: PrimeAdminService = Depends(get_prime_admin_service),
) -> List[PrimeZoneRead]:
    """Prime delivery zones with their pincode counts (staff only)."""
    return await service.list_zones(current_tenant.id, current_user)


@router.get("/prime-lanes", response_model=List[PrimeLaneRead])
async def list_prime_lanes(
    *,
    active_only: bool = Query(False, description="Only the active lane of each route"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: PrimeAdminService = Depends(get_prime_admin_service),
) -> List[PrimeLaneRead]:
    """Prime lanes with zone names (staff only)."""
    return await service.list_lanes(current_tenant.id, current_user, active_only=active_only)


@router.get(
    "/prime-lanes/export.csv",
    response_class=Response,
    responses={200: {"content": {CSV_MEDIA_TYPE: {}}, "description": "Lanes CSV in the import format"}},
)
async def export_prime_lanes(
    *,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: PrimeAdminService = Depends(get_prime_admin_service),
) -> Response:
    """All lanes as CSV, re-importable through `POST /prime-lanes/import` (staff only)."""
    content = await service.export_csv(current_tenant.id, current_user)
    return Response(
        content=content,
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{EXPORT_FILENAME}"'},
    )


@router.get(
    "/prime-lanes/template.csv",
    response_class=Response,
    responses={200: {"content": {CSV_MEDIA_TYPE: {}}, "description": "Sample Prime lanes CSV template"}},
)
@router.get("/prime-lanes/template-csv", response_class=Response, include_in_schema=False)
@router.get("/prime-lanes/template", response_class=Response, include_in_schema=False)
async def download_prime_lanes_template(
    *,
    current_user: User = Depends(get_current_active_user),
    service: PrimeAdminService = Depends(get_prime_admin_service),
) -> Response:
    """Sample CSV template with headers and 2 example rows for `POST /prime-lanes/import` (staff only)."""
    content = service.template_csv(current_user)
    return Response(
        content=content,
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_FILENAME}"'},
    )


@router.patch("/prime-lanes/{lane_id}", response_model=PrimeLaneRead)
async def update_prime_lane(
    *,
    lane_id: uuid.UUID,
    patch: PrimeLanePatch,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: PrimeAdminService = Depends(get_prime_admin_service),
) -> PrimeLaneRead:
    """Edits a lane's numbers and/or active flag (owner/admin)."""
    return await service.patch_lane(current_tenant.id, current_user, lane_id, patch)


@router.post("/prime-lanes/import", response_model=PrimeImportReport)
async def import_prime_lanes(
    *,
    dry_run: bool = Query(True, description="Report only; write nothing"),
    content: bytes = Body(..., media_type=CSV_MEDIA_TYPE, description="Lanes CSV in the export format"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: PrimeAdminService = Depends(get_prime_admin_service),
) -> PrimeImportReport:
    """Imports lanes from CSV (owner/admin); any error writes nothing."""
    return await service.import_csv(current_tenant.id, current_user, content, dry_run=dry_run)
