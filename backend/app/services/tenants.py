import uuid

from app.core.db import get_session
from app.core.security import TokenPayload
from app.exceptions.definitions import TenantNotFoundException
from app.models.tenants import Tenant, User, UserRole
from app.repositories.tenants import TenantRepository
from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession


class TenantService:
    """
    This class handles the business logic for tenants and users.
    It depends on the TenantRepository for data access.
    """

    def __init__(self, tenant_repo: TenantRepository):
        self.tenant_repo = tenant_repo

    async def get_or_create_user(
        self, *, token_data: TokenPayload, tenant: Tenant
    ) -> User:
        """
        Gets a user profile if it exists, or creates a new one if it does not.
        This is the core "Just-in-Time" provisioning logic.
        """
        # Use the repository to find the user
        user = await self.tenant_repo.get_user_by_supabase_id_and_tenant_id(
            supabase_user_id=token_data.sub, tenant_id=tenant.id
        )

        if user:
            return user

        # If user does not exist, create a new user profile
        new_user = User(
            email=token_data.email,
            supabase_user_id=token_data.sub,
            tenant_id=tenant.id,
            role=UserRole.customer,  # New users default to 'customer'
            is_active=True,
        )
        # Use the repository to save the new user
        return await self.tenant_repo.create_user(new_user)

    async def list_tenants(self) -> list[Tenant]:
        """
        Retrieves all tenants from the repository.
        """
        return await self.tenant_repo.list_tenants()

    async def list_users_for_tenant(self, tenant_id: uuid.UUID) -> list[User]:
        """
        Retrieves all users for a specific tenant.
        """
        tenant = await self.tenant_repo.get_tenant_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        return await self.tenant_repo.list_users_for_tenant(tenant_id=tenant_id)


# This is a factory function that FastAPI will use for dependency injection.
# It creates a TenantRepository with a session and then creates our service.
def get_tenant_service(session: AsyncSession = Depends(get_session)) -> TenantService:
    """
    Factory for creating a TenantService instance with its dependencies.
    """
    tenant_repo = TenantRepository(session)
    return TenantService(tenant_repo)
