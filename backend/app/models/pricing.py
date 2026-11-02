"""
Pricing redesign tables owned by the Delhivery side (M-P1, 9a1b2c3d4e5f).

- `delhivery_price_cache`: Delhivery's price answers per tenant, keyed by the exact
  request (origin/destination pin, mode, leg, payment type, 500 g slab). Reused for
  30 minutes on "Get rates" and as the 24-hour fallback at Book when Delhivery is down
  (user decision Q6). Per tenant because prices are per Delhivery account.
  Deny-all row-level security in the database (only the backend reads it).

Spring analogy: a plain `@Entity DelhiveryPriceCache` with a composite unique key.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import sqlalchemy as sa
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

CACHE_KEY_MAX_LENGTH = 200
"""Width of `delhivery_price_cache.cache_key` (VARCHAR(200))."""


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (TIMESTAMP WITHOUT TIME ZONE columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DelhiveryPriceCache(SQLModel, table=True):
    """One stored Delhivery price answer (`resp[0]` of the invoice/charges API)."""

    __tablename__ = "delhivery_price_cache"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid, sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
        )
    )
    cache_key: str = Field(sa_column=Column(sa.String(CACHE_KEY_MAX_LENGTH), nullable=False))
    request_params: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    response: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    fetched_at: datetime = Field(
        default_factory=_utc_now_naive,
        sa_column=Column(sa.DateTime(timezone=False), nullable=False),
    )
