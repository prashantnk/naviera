import uuid

from app.models.tenants import Tenant, User
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


class TenantRepository:
    """
    This class handles all database operations for Tenant and related models.
    It depends on an AsyncSession from the dependency injection system.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_tenants(self) -> list[Tenant]:
        """
        Retrieves all tenants from the database.
        """
        statement = select(Tenant)
        result = await self.session.exec(statement)
        return list(result.all())

    async def get_tenant_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        """
        Retrieves a single tenant by its ID.
        """
        return await self.session.get(Tenant, tenant_id)

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        """
        Retrieves a single tenant by its unique slug.
        """
        statement = select(Tenant).where(Tenant.slug == slug)
        result = await self.session.exec(statement)
        return result.first()

    async def list_users_for_tenant(self, tenant_id: uuid.UUID) -> list[User]:
        """
        Retrieves all users for a specific tenant.
        """
        statement = select(User).where(User.tenant_id == tenant_id)
        result = await self.session.exec(statement)
        return list(result.all())

    async def get_user_by_supabase_id_and_tenant_id(
        self, *, supabase_user_id: str, tenant_id: uuid.UUID
    ) -> User | None:
        """
        Retrieves a single user profile based on the supabase_user_id
        and tenant_id.
        """
        statement = select(User).where(
            User.supabase_user_id == supabase_user_id,
            User.tenant_id == tenant_id,
        )
        result = await self.session.exec(statement)
        return result.first()

    async def create_user(self, user: User) -> User:
        """
        Adds a new User object to the database.
        """
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
