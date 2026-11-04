import json
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import delete, desc, text
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import cache_tenant, cache_user, invalidate_auth_cache
from app.models.tenants import Tenant, TenantSettingsHistory, User

DEFAULT_SUPABASE_INSTANCE_ID = "00000000-0000-0000-0000-000000000000"


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

    async def get_user_by_email_and_tenant_id(
        self, *, email: str, tenant_id: uuid.UUID
    ) -> User | None:
        """
        Retrieves a single user profile by case-insensitive email and tenant_id.
        """
        statement = select(User).where(
            func.lower(User.email) == email.strip().lower(),
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
        invalidate_auth_cache(
            tenant_id=user.tenant_id, supabase_user_id=user.supabase_user_id
        )
        cache_user(user)
        return user

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Retrieves a single user by ID."""
        return await self.session.get(User, user_id)

    async def get_tenant_for_update(self, tenant_id: uuid.UUID) -> Tenant | None:
        """Locks the tenant row so concurrent settings saves get sequential versions."""
        statement = select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        result = await self.session.exec(statement)
        return result.first()

    async def next_settings_version(self, tenant_id: uuid.UUID) -> int:
        """1 + the highest stored version for the tenant (1 for the first snapshot)."""
        statement = select(func.max(TenantSettingsHistory.version)).where(
            TenantSettingsHistory.tenant_id == tenant_id
        )
        current_max = (await self.session.exec(statement)).one()
        return int(current_max or 0) + 1

    async def add_settings_snapshot(self, snapshot: TenantSettingsHistory) -> None:
        """Stages a snapshot row (flushed, not committed)."""
        self.session.add(snapshot)
        await self.session.flush()

    async def prune_settings_history(
        self,
        tenant_id: uuid.UUID,
        keep: int,
        protected_sections: Tuple[str, ...] = (
            "pricing_config",
            "pricing_policy",
            "wallet_config",
            "gstin",
            "company",
            "user_roles",
        ),
    ) -> None:
        """
        Deletes all but the newest `keep` snapshots of a tenant, while never pruning
        snapshots that touched financial, tax, or role sections (G-10).
        """
        rows_stmt = (
            select(TenantSettingsHistory.id, TenantSettingsHistory.changed_sections)
            .where(TenantSettingsHistory.tenant_id == tenant_id)
            .order_by(desc(col(TenantSettingsHistory.version)))
        )
        rows = (await self.session.exec(rows_stmt)).all()
        if len(rows) <= keep:
            return
        protected_set = frozenset(protected_sections)
        non_protected_seen = 0
        delete_ids: List[uuid.UUID] = []
        for snap_id, sections in rows:
            sec_list = sections if isinstance(sections, list) else []
            if protected_set.intersection(sec_list):
                continue
            non_protected_seen += 1
            if non_protected_seen > keep:
                delete_ids.append(snap_id)
        if delete_ids:
            statement = delete(TenantSettingsHistory).where(
                col(TenantSettingsHistory.tenant_id) == tenant_id,
                col(TenantSettingsHistory.id).in_(delete_ids),
            )
            await self.session.exec(statement)  # type: ignore[call-overload]

    async def list_settings_history(
        self, tenant_id: uuid.UUID
    ) -> List[Tuple[TenantSettingsHistory, Optional[str]]]:
        """Snapshots (newest first) with the editor's email (None if unknown / deleted)."""
        statement = (
            select(TenantSettingsHistory, User.email)
            .join(User, col(User.id) == col(TenantSettingsHistory.changed_by_user_id), isouter=True)
            .where(TenantSettingsHistory.tenant_id == tenant_id)
            .order_by(desc(col(TenantSettingsHistory.version)))
        )
        rows = (await self.session.exec(statement)).all()
        return [(row[0], row[1]) for row in rows]

    async def get_settings_snapshot(
        self, snapshot_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[TenantSettingsHistory]:
        """One snapshot, tenant-scoped."""
        statement = select(TenantSettingsHistory).where(
            TenantSettingsHistory.id == snapshot_id,
            TenantSettingsHistory.tenant_id == tenant_id,
        )
        return (await self.session.exec(statement)).first()

    async def save_tenant(self, tenant: Tenant) -> Tenant:
        """Stages tenant changes without committing (caller owns the transaction)."""
        self.session.add(tenant)
        await self.session.flush()
        invalidate_auth_cache(tenant_id=tenant.id, slug=tenant.slug)
        return tenant

    async def commit_and_refresh(self, tenant: Tenant) -> Tenant:
        """Commits the unit of work and reloads the tenant."""
        await self.session.commit()
        await self.session.refresh(tenant)
        invalidate_auth_cache(tenant_id=tenant.id, slug=tenant.slug)
        cache_tenant(tenant)
        return tenant

    async def get_auth_user_by_email(self, email: str) -> Optional[dict]:
        """Looks up a Supabase auth.users record by case-insensitive email."""
        stmt = text(
            "SELECT id::text AS id, email, "
            "(encrypted_password IS NOT NULL AND encrypted_password <> '') AS has_password "
            "FROM auth.users "
            "WHERE lower(email) = :email AND deleted_at IS NULL "
            "LIMIT 1"
        )
        res = await self.session.execute(stmt, {"email": email.strip().lower()})
        row = res.mappings().first()
        return dict(row) if row else None

    async def verify_auth_user_password(
        self, email: str, password: str
    ) -> Optional[dict]:
        """Verifies email + password against confirmed auth.users using pgcrypto bcrypt (B-04)."""
        stmt = text(
            "SELECT id::text AS id, email "
            "FROM auth.users "
            "WHERE lower(email) = :email "
            "AND deleted_at IS NULL "
            "AND email_confirmed_at IS NOT NULL "
            "AND encrypted_password IS NOT NULL "
            "AND encrypted_password <> '' "
            "AND encrypted_password = extensions.crypt(:password, encrypted_password) "
            "LIMIT 1"
        )
        res = await self.session.execute(
            stmt, {"email": email.strip().lower(), "password": password}
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def create_auth_user_with_password(
        self,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        extra_user_metadata: Optional[dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Creates a confirmed Supabase auth.users record with a bcrypt password hash.

        Args:
            extra_user_metadata: Additional `raw_user_meta_data` keys (e.g. the
                signup consent `terms_accepted_at` / `terms_version`). They can
                never override the identity keys (email, sub, verification flags).

        Returns:
            The new auth user id, or None when a row for the email already exists
            (unique-index conflict, e.g. a concurrent signup). Existing rows are
            never modified.
        """
        new_id = str(uuid.uuid4())
        normalized_email = email.strip().lower()
        user_meta = {
            **(extra_user_metadata or {}),
            "email": normalized_email,
            "email_verified": True,
            "phone_verified": False,
            "sub": new_id,
        }
        if full_name and full_name.strip():
            user_meta["full_name"] = full_name.strip()

        stmt = text(
            "INSERT INTO auth.users ("
            "instance_id, id, aud, role, email, encrypted_password, "
            "email_confirmed_at, last_sign_in_at, raw_app_meta_data, "
            "raw_user_meta_data, created_at, updated_at, is_sso_user, is_anonymous"
            ") VALUES ("
            "CAST(:instance_id AS uuid), CAST(:uid AS uuid), 'authenticated', 'authenticated', "
            ":email, extensions.crypt(:password, extensions.gen_salt('bf')), "
            "now(), now(), "
            "CAST(:app_meta AS jsonb), CAST(:user_meta AS jsonb), "
            "now(), now(), false, false"
            ") ON CONFLICT DO NOTHING "
            "RETURNING id::text AS id"
        )
        res = await self.session.execute(
            stmt,
            {
                "instance_id": DEFAULT_SUPABASE_INSTANCE_ID,
                "uid": new_id,
                "email": normalized_email,
                "password": password,
                "app_meta": json.dumps({"provider": "email", "providers": ["email"]}),
                "user_meta": json.dumps(user_meta),
            },
        )
        inserted = res.mappings().first()
        await self.session.flush()
        return str(inserted["id"]) if inserted else None
