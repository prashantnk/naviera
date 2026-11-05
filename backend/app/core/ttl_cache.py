"""
Bounded, thread-safe, in-process TTL + LRU cache shared by every backend read cache.

Why one helper: the auth, address and pickup-request caches must all be bounded (Render
Free has 512 MB), purge expired entries, hand out detached copies, and be invalidated on
EVERY committed write, not only on the write paths someone remembered to wire up.

Invalidation is automatic. Each cache declares the ORM models it is derived from
(`invalidated_by`). SQLAlchemy session events record every new / dirty / deleted instance
of those models at flush time and evict the matching tenant's entries at flush, at commit
and at rollback, so ANY write that goes through the ORM (services, ops, exceptions, the
temporal-hooks worker, bulk actions) evicts the cache in this process.

Races: `generation()` is captured before a cache-miss load and passed to `set()`; a load
that overlapped an invalidation is not stored, so a slow reader can never re-insert data
that a concurrent commit already replaced.

Staleness bound: writes made by OTHER processes (a second uvicorn worker, seed / reset
scripts, SQL run in Supabase) are not seen until the entry's TTL expires.

Spring Boot equivalent: a Caffeine cache (`maximumSize` + `expireAfterWrite`) evicted by a
Hibernate `PostCommitUpdateEventListener`.
"""

import copy
import sys
import threading
import time
import uuid
from collections import OrderedDict
from itertools import chain
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Hashable,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
)

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

ALL_TENANTS: Optional[uuid.UUID] = None
"""Tenant marker for "evict every tenant" (writes to rows that carry no tenant id)."""

_PENDING_INVALIDATIONS_KEY = "ttl_cache_pending_invalidations"
"""`Session.info` key holding the (cache, tenant_id) pairs flushed in the open transaction."""

_enabled_override: Optional[bool] = None
_registry: List["TTLCache[Any, Any]"] = []


def caches_enabled() -> bool:
    """Caches are off inside pytest (DB-backed suites share rows) unless a test opts in."""
    if _enabled_override is not None:
        return _enabled_override
    return "pytest" not in sys.modules


def set_caches_enabled_for_tests(enabled: Optional[bool]) -> None:
    """Forces every cache on/off (None restores the default) and empties them all."""
    global _enabled_override
    _enabled_override = enabled
    clear_all_caches()


def clear_all_caches() -> None:
    """Empties every registered cache."""
    for cache in _registry:
        cache.invalidate(ALL_TENANTS)


def all_cache_stats() -> List[Dict[str, Any]]:
    """Hit / miss / size counters of every registered cache (for logs and the soak test)."""
    return [cache.stats() for cache in _registry]


def _first_key_part(key: Any, _value: Any) -> Optional[uuid.UUID]:
    """Default tenant resolver: cache keys are tuples that start with `tenant_id`."""
    return key[0]


class TTLCache(Generic[K, V]):
    """
    A size-bounded LRU map whose entries expire `ttl_seconds` after they were stored.

    Args:
        name: Label used in stats.
        ttl_seconds: Entry lifetime (also the cross-process staleness bound).
        max_entries: Hard cap; the least recently used entry is evicted beyond it.
        clone: Copies a value on the way in and on the way out, so callers can never
            mutate shared state and cached ORM rows are never attached to a session.
        invalidated_by: ORM model -> name of its tenant-id attribute (None when the row
            has no tenant id, which evicts every tenant).
        tenant_of: Resolves the owning tenant of an entry from (key, value).
        max_items_per_entry: Lists longer than this are served but not stored, so one
            huge tenant-wide list can never pin a large slice of the 512 MB budget.
    """

    def __init__(
        self,
        name: str,
        *,
        ttl_seconds: float,
        max_entries: int,
        clone: Callable[[V], V] = copy.deepcopy,
        invalidated_by: Mapping[Type[Any], Optional[str]],
        tenant_of: Callable[[K, V], Optional[uuid.UUID]] = _first_key_part,
        max_items_per_entry: Optional[int] = None,
    ) -> None:
        self.name = name
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.invalidated_by = dict(invalidated_by)
        self._clone = clone
        self._tenant_of = tenant_of
        self._max_items_per_entry = max_items_per_entry
        self._lock = threading.Lock()
        self._entries: "OrderedDict[K, Tuple[float, Optional[uuid.UUID], V]]" = OrderedDict()
        self._generation = 0
        self._next_purge_at = 0.0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        _registry.append(self)

    def generation(self) -> int:
        """Snapshot to pass to `set()`; any invalidation in between discards the store."""
        with self._lock:
            return self._generation

    def get(self, key: K) -> Optional[V]:
        """A detached copy of the live entry, or None (expired entries are dropped)."""
        if not caches_enabled():
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry[0] <= now:
                if entry is not None:
                    del self._entries[key]
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            value = entry[2]
        return self._clone(value)

    def set(self, key: K, value: V, *, generation: Optional[int] = None) -> V:
        """
        Stores a detached copy and returns another one. Not stored when the value is an
        over-long list or an invalidation happened since `generation`. With caching off
        the value is returned untouched.
        """
        if not caches_enabled():
            return value
        stored = self._clone(value)
        if self._too_large(stored):
            return self._clone(stored)
        tenant_id = self._tenant_of(key, stored)
        now = time.monotonic()
        with self._lock:
            if generation is None or generation == self._generation:
                self._entries[key] = (now + self.ttl_seconds, tenant_id, stored)
                self._entries.move_to_end(key)
                self._evict_locked(now)
        return self._clone(stored)

    async def get_or_load(
        self, key: K, loader: Callable[[], Awaitable[Optional[V]]]
    ) -> Optional[V]:
        """Cache-aside read. A None result (e.g. unknown slug) is never cached."""
        cached = self.get(key)
        if cached is not None:
            return cached
        generation = self.generation()
        value = await loader()
        if value is None:
            return None
        return self.set(key, value, generation=generation)

    def invalidate(self, tenant_id: Optional[uuid.UUID] = ALL_TENANTS) -> None:
        """Evicts one tenant's entries (or all) and voids in-flight loads."""
        with self._lock:
            self._generation += 1
            if tenant_id is ALL_TENANTS:
                self._entries.clear()
                return
            stale = [k for k, (_, owner, _) in self._entries.items() if owner == tenant_id]
            for key in stale:
                del self._entries[key]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "size": len(self._entries),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    def _too_large(self, value: Any) -> bool:
        limit = self._max_items_per_entry
        return limit is not None and isinstance(value, list) and len(value) > limit

    def _evict_locked(self, now: float) -> None:
        """
        Purges expired entries (when over the cap, and at most once per TTL otherwise, so
        a store stays O(1) amortised), then the least recently used ones beyond the cap.
        """
        if len(self._entries) > self.max_entries or now >= self._next_purge_at:
            self._next_purge_at = now + self.ttl_seconds
            expired = [k for k, (expires_at, _, _) in self._entries.items() if expires_at <= now]
            for key in expired:
                del self._entries[key]
            self._evictions += len(expired)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1


# --------------------------------------------------------------------------------------
# Automatic ORM invalidation (flush -> commit / rollback)
# --------------------------------------------------------------------------------------


def _tenant_id_of(instance: Any, attr: Optional[str]) -> Optional[uuid.UUID]:
    """Reads the tenant id from the instance dict without triggering a lazy load."""
    if attr is None:
        return ALL_TENANTS
    return inspect(instance).dict.get(attr, ALL_TENANTS)


def pending_invalidations(
    instances: Iterable[Any],
) -> Set[Tuple["TTLCache[Any, Any]", Optional[uuid.UUID]]]:
    """(cache, tenant_id) pairs that the given written ORM instances make stale."""
    pending: Set[Tuple[TTLCache[Any, Any], Optional[uuid.UUID]]] = set()
    for instance in instances:
        model = type(instance)
        for cache in _registry:
            if model in cache.invalidated_by:
                pending.add((cache, _tenant_id_of(instance, cache.invalidated_by[model])))
    return pending


def _apply(pending: Iterable[Tuple["TTLCache[Any, Any]", Optional[uuid.UUID]]]) -> None:
    for cache, tenant_id in pending:
        cache.invalidate(tenant_id)


@event.listens_for(Session, "after_flush")
def _invalidate_after_flush(session: Session, _flush_context: Any) -> None:
    """Records what the flush wrote and evicts it now (no reader may cache pre-commit state)."""
    flushed = pending_invalidations(chain(session.new, session.dirty, session.deleted))
    if not flushed:
        return
    session.info.setdefault(_PENDING_INVALIDATIONS_KEY, set()).update(flushed)
    _apply(flushed)


@event.listens_for(Session, "after_commit")
def _invalidate_after_commit(session: Session) -> None:
    """Evicts again once the rows are visible to other sessions."""
    _apply(session.info.pop(_PENDING_INVALIDATIONS_KEY, ()))


@event.listens_for(Session, "after_soft_rollback")
def _invalidate_after_rollback(session: Session, _previous_transaction: Any) -> None:
    """Evicts anything cached from the rolled-back (never committed) state."""
    _apply(session.info.pop(_PENDING_INVALIDATIONS_KEY, ()))
