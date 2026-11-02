"""
Staff editor of the selling policy: `GET/PUT /api/v1/pricing/policy` (DESIGN.md v4 §C.2).

Kept apart from `policy.py` (pure reads used by quoting and re-pricing) because it depends
on `TenantService` (settings history), which would otherwise create an import cycle with
`repricing.py`.

Spring analogy: a `@Service` with `@PreAuthorize`-style role checks on the write path.
"""

import uuid

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.permissions import is_tenant_staff
from app.models.tenants import Tenant, User, UserRole
from app.repositories.tenants import TenantRepository
from app.schemas.v1.pricing import PricingPolicy, PricingPolicyRead
from app.services.pricing.policy import PRICING_POLICY_SETTINGS_KEY, policy_of, to_read
from app.services.tenants import TenantService

POLICY_WRITER_ROLES = (UserRole.owner, UserRole.admin)
STAFF_ONLY_DETAIL = "Only Logismart staff can view the pricing policy."
WRITER_ONLY_DETAIL = "Only an Owner or Admin can change the pricing policy."


class PricingPolicyService:
    """Read (staff) and replace (owner/admin) the selling policy."""

    def __init__(self, tenant_service: TenantService) -> None:
        self.tenant_service = tenant_service

    @staticmethod
    def _assert_staff(user: User) -> None:
        """Customers never see markups or the COD fee configuration."""
        if not is_tenant_staff(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STAFF_ONLY_DETAIL)

    async def get_policy(self, tenant: Tenant, user: User) -> PricingPolicyRead:
        """
        The current policy (defaults when unset or invalid, so the editor can repair it).

        Raises:
            HTTPException(403): not tenant staff.
        """
        self._assert_staff(user)
        return to_read(tenant, policy_of(tenant) or PricingPolicy())

    async def replace_policy(
        self, tenant_id: uuid.UUID, policy: PricingPolicy, user: User
    ) -> PricingPolicyRead:
        """
        Replaces the whole policy block (row-locked + settings history snapshot).

        Raises:
            HTTPException(403): not owner/admin.
        """
        self._assert_staff(user)
        if user.role not in POLICY_WRITER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=WRITER_ONLY_DETAIL)
        tenant = await self.tenant_service.replace_settings_section(
            tenant_id, user, PRICING_POLICY_SETTINGS_KEY, policy.model_dump(mode="json")
        )
        return to_read(tenant, policy)


def get_pricing_policy_service(session: AsyncSession = Depends(get_session)) -> PricingPolicyService:
    """FastAPI provider (Spring: constructor injection of the session-scoped service)."""
    return PricingPolicyService(TenantService(TenantRepository(session)))
