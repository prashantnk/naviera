"""
Data access for `delhivery_price_cache` (M-P1). Every query filters `tenant_id`.

Spring analogy: a `JpaRepository<DelhiveryPriceCache, UUID>` plus one native
`INSERT … ON CONFLICT DO UPDATE` upsert.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pricing import DelhiveryPriceCache


class DelhiveryPriceCacheRepository:
    """Reads and upserts stored Delhivery price answers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: uuid.UUID, cache_key: str) -> Optional[DelhiveryPriceCache]:
        """The stored answer for one exact request, or None."""
        statement = select(DelhiveryPriceCache).where(
            col(DelhiveryPriceCache.tenant_id) == tenant_id,
            col(DelhiveryPriceCache.cache_key) == cache_key,
        )
        return (await self.session.exec(statement)).first()

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        cache_key: str,
        request_params: Dict[str, Any],
        response: Dict[str, Any],
        fetched_at: datetime,
    ) -> None:
        """Stores (or refreshes) the answer for `cache_key`; flushed with the caller's transaction."""
        statement = insert(DelhiveryPriceCache.__table__).values(  # type: ignore[attr-defined]
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            cache_key=cache_key,
            request_params=request_params,
            response=response,
            fetched_at=fetched_at,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_delhivery_price_cache_tenant_key",
            set_={
                "request_params": statement.excluded.request_params,
                "response": statement.excluded.response,
                "fetched_at": statement.excluded.fetched_at,
            },
        )
        await self.session.exec(statement)  # type: ignore[call-overload]
