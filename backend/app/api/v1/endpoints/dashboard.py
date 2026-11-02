from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.manifests import ServiceFlow
from app.models.tenants import Tenant, User
from app.schemas.v1.dashboard import DASHBOARD_DEFAULT_DAYS, DashboardSummaryResponse
from app.services.dashboard import DashboardService

router = APIRouter()


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    *,
    service_flow: ServiceFlow = Query(..., description="B2C (Domestic) or B2B (Surface)"),
    days: int = Query(DASHBOARD_DEFAULT_DAYS, description="Window in days: 7, 14 or 30"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Home dashboard summary for shipments created in the last `days`
    (tenant-wide for Admin/Owner, own shipments for customers).
    """
    service = DashboardService(session)
    return await service.get_summary(
        current_tenant.id, current_user, service_flow=service_flow, days=days
    )
