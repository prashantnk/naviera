"""
Pricing redesign endpoints (DESIGN.md v4; contract `llm_resources/.agents/pricing/API_CONTRACT.md`).

- `POST /api/v1/quotes`: option cards for the rate calculator and the booking forms.
- `GET/PUT /api/v1/pricing/policy`: the staff-only selling policy (owner/admin write).

Controllers only: validation + dependency injection; logic lives in `services/pricing/`.
Spring analogy: two `@RestController`s with `@RequestMapping("/quotes")` and `("/pricing")`.
"""

import logging

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.tenants import Tenant, User
from app.schemas.v1.pricing import (
    PricingPolicy,
    PricingPolicyRead,
    QuoteRequest,
    QuoteResponse,
)
from app.services.pricing.policy_admin import (
    PricingPolicyService,
    get_pricing_policy_service,
)
from app.services.pricing.quote_service import QuoteService

logger = logging.getLogger(__name__)

quotes_router = APIRouter()
pricing_router = APIRouter()


@quotes_router.post("", response_model=QuoteResponse)
async def get_quotes(
    payload: QuoteRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
) -> QuoteResponse:
    """
    Prices every option of the flow on the exact booking inputs (A-03).
    Greyed-out options carry a plain-English `unavailable_reason`; nothing is booked.
    """
    logger.info("API Request: quotes (%s) for tenant '%s'", payload.service_flow.value, current_tenant.slug)
    return await QuoteService(session).quote_options(current_tenant, payload)


@pricing_router.get("/policy", response_model=PricingPolicyRead)
async def get_pricing_policy(
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: PricingPolicyService = Depends(get_pricing_policy_service),
) -> PricingPolicyRead:
    """The selling policy (tenant staff only; customers get 403)."""
    return await service.get_policy(current_tenant, current_user)


@pricing_router.put("/policy", response_model=PricingPolicyRead)
async def replace_pricing_policy(
    payload: PricingPolicy,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: PricingPolicyService = Depends(get_pricing_policy_service),
) -> PricingPolicyRead:
    """Replaces the whole policy (Owner/Admin only); the previous settings are snapshotted."""
    return await service.replace_policy(current_tenant.id, payload, current_user)
