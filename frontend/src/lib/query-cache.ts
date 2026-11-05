// frontend/src/lib/query-cache.ts
/**
 * Lightweight client-side Stale-While-Revalidate (SWR) in-memory query cache.
 *
 * Why this exists:
 * Navigating back and forth across authenticated workspace screens (`Home`,
 * `Orders`, `Pickup Requests`, `Delivery Exceptions`, `Wallet`, `Remittances`,
 * `Invoices`, `Support`, `Weight Mismatch`) previously initialized every screen
 * with `loading = true` and waited 300ms–2000ms for a fresh network round-trip
 * before painting any rows.
 *
 * With `query-cache.ts`:
 * 1. Screens read their last known payload synchronously during `useState(...)`
 *    initialization, rendering cached data in `0ms` with zero spinner flash.
 * 2. Every screen still revalidates in the background (`useEffect`) and updates
 *    both state and cache when the response arrives.
 * 3. Any mutation (`POST`, `PUT`, `PATCH`, `DELETE`) observed by the Axios
 *    interceptor in `api-config.ts` or any `wallet-updated` window event
 *    automatically invalidates the cache so stale financial or status data is
 *    never shown after an action. Invalidations are broadcast to other tabs.
 *
 * Safety rails (rel8):
 * - Every key embeds the signed-in Supabase user id read from the tenant's
 *   stored session, so a different user (same tab, or another tab that signed
 *   in as someone else) can never read the previous user's entries.
 * - The cache is an LRU bounded to `MAX_QUERY_CACHE_ENTRIES`; expired entries
 *   are swept periodically, so a long session with many search/filter keys
 *   cannot grow the heap without limit.
 * - Only the latest request for a key may write it, and invalidation forgets
 *   in-flight requests, so a slow pre-mutation GET cannot resurrect stale data.
 * - The cache is disabled on the server (SSR), so one user's data can never be
 *   shared through a server process.
 */

export const DEFAULT_QUERY_CACHE_TTL_MS = 60_000;

/** Upper bound on cached responses; the least recently used entry is evicted first. */
export const MAX_QUERY_CACHE_ENTRIES = 100;

/** Minimum gap between full sweeps of expired entries. */
const EXPIRED_SWEEP_INTERVAL_MS = 30_000;

/** Cross-tab channel carrying invalidations. */
const BROADCAST_CHANNEL_NAME = "naviera-query-cache";

/** `localStorage` keys holding a tenant's Supabase session (`sb-<slug>-auth-token`). */
const SESSION_STORAGE_KEY_PATTERN = /^sb-.+-auth-token$/;

/** Identity segment used when no signed-in user is found. */
const ANONYMOUS_IDENTITY = "anon";

interface CacheEntry<T = unknown> {
  data: T;
  expiresAt: number;
}

interface InvalidationMessage {
  matchToken?: string;
}

/** Map iteration order is insertion order, which makes it a cheap LRU. */
const memoryCache = new Map<string, CacheEntry>();
const inFlightRequests = new Map<string, Promise<unknown>>();
const sessionIdentityByTenant = new Map<string, { raw: string | null; userId: string }>();

let lastSweepAt = 0;
let testOverrideEnabled = false;
let broadcastChannel: BroadcastChannel | null | undefined;

function _isCacheActive(): boolean {
  if (typeof window === "undefined") return false;
  if (testOverrideEnabled) return true;
  if (typeof process !== "undefined" && Boolean(process.env?.VITEST)) {
    return false;
  }
  return true;
}

function _stableSerialize(params?: Record<string, unknown>): string {
  if (!params) return "";
  const keys = Object.keys(params).sort();
  const parts: string[] = [];
  for (const key of keys) {
    const val = params[key];
    if (val === undefined) continue;
    parts.push(`${key}=${JSON.stringify(val)}`);
  }
  return parts.join("&");
}

/**
 * Extracts `user.id` from a serialized Supabase session.
 *
 * @param raw - Value of `sb-<slug>-auth-token`, or null.
 * @returns The user id, or `anon` when absent or unparsable.
 */
function _userIdFromSession(raw: string | null): string {
  if (!raw) return ANONYMOUS_IDENTITY;
  try {
    const parsed = JSON.parse(raw) as { user?: { id?: unknown } };
    const userId = parsed?.user?.id;
    return typeof userId === "string" && userId ? userId : ANONYMOUS_IDENTITY;
  } catch {
    return ANONYMOUS_IDENTITY;
  }
}

/**
 * Returns the signed-in user id for `tenantSlug` from the stored session.
 * The parse is memoized on the raw string, so a render costs one `getItem`.
 *
 * @param tenantSlug - Tenant whose `sb-<slug>-auth-token` is read.
 * @returns User id, or `anon`.
 */
function _sessionIdentity(tenantSlug: string): string {
  if (typeof window === "undefined" || !tenantSlug) return ANONYMOUS_IDENTITY;
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(`sb-${tenantSlug}-auth-token`);
  } catch {
    return ANONYMOUS_IDENTITY;
  }
  const memo = sessionIdentityByTenant.get(tenantSlug);
  if (memo && memo.raw === raw) return memo.userId;
  const userId = _userIdFromSession(raw);
  sessionIdentityByTenant.set(tenantSlug, { raw, userId });
  return userId;
}

/**
 * Builds a deterministic, tenant- and user-scoped cache key.
 *
 * The signed-in user's id (from the tenant's stored Supabase session) is always
 * part of the key, so callers only choose a view scope such as `staff`.
 *
 * @param tenantSlug - Active tenant slug (`logismart`, `logismart-test`, ...).
 * @param scopeKey - View scope within that user (`session`, `staff`, `customer`, ...).
 * @param endpoint - Logical resource name (`dashboard`, `shipments`, ...).
 * @param params - Query parameters distinguishing the request.
 * @returns Canonical cache key string.
 */
export function buildQueryCacheKey(
  tenantSlug: string | null | undefined,
  scopeKey?: string | null | undefined,
  endpoint: string = "",
  params?: Record<string, unknown>,
): string {
  const rawTenant = (tenantSlug || "").trim();
  const cleanTenant = (rawTenant || "default").toLowerCase();
  const identity = _sessionIdentity(rawTenant).toLowerCase();
  const cleanScope = (scopeKey || "anon").trim().toLowerCase();
  const cleanEndpoint = endpoint.trim().toLowerCase();
  return `${cleanTenant}::${identity}::${cleanScope}::${cleanEndpoint}::${_stableSerialize(params)}`;
}

/** Drops expired entries at most once per `EXPIRED_SWEEP_INTERVAL_MS`. */
function _sweepExpired(now: number): void {
  if (now - lastSweepAt < EXPIRED_SWEEP_INTERVAL_MS) return;
  lastSweepAt = now;
  for (const [key, entry] of memoryCache) {
    if (now > entry.expiresAt) memoryCache.delete(key);
  }
}

/**
 * Reads a non-expired cached response synchronously and marks it recently used.
 *
 * @param key - Cache key from `buildQueryCacheKey`.
 * @returns Cached value or `null` when missing/expired.
 */
export function getCachedQuery<T>(key: string): T | null {
  if (!key || !_isCacheActive()) return null;
  const entry = memoryCache.get(key);
  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    memoryCache.delete(key);
    return null;
  }
  memoryCache.delete(key);
  memoryCache.set(key, entry);
  return entry.data as T;
}

/**
 * Checks whether a non-expired cache entry exists for `key`.
 *
 * @param key - Cache key from `buildQueryCacheKey`.
 * @returns True when `getCachedQuery(key)` would return a value.
 */
export function hasCachedQuery(key: string): boolean {
  return getCachedQuery(key) !== null;
}

/**
 * Stores a response in the in-memory SWR cache, evicting the least recently
 * used entries beyond `MAX_QUERY_CACHE_ENTRIES`.
 *
 * @param key - Cache key from `buildQueryCacheKey`.
 * @param data - Response payload to cache.
 * @param ttlMs - Time-to-live in milliseconds (default 60s).
 * @returns The stored `data` for convenient chaining.
 */
export function setCachedQuery<T>(
  key: string,
  data: T,
  ttlMs: number = DEFAULT_QUERY_CACHE_TTL_MS,
): T {
  if (!key || !_isCacheActive()) return data;
  const now = Date.now();
  memoryCache.delete(key);
  memoryCache.set(key, { data, expiresAt: now + ttlMs });
  _sweepExpired(now);
  while (memoryCache.size > MAX_QUERY_CACHE_ENTRIES) {
    const oldestKey = memoryCache.keys().next().value;
    if (oldestKey === undefined) break;
    memoryCache.delete(oldestKey);
  }
  return data;
}

/**
 * Fetches data using `fetcher`, returning cached data immediately when warm
 * (unless `options.force` is true), deduplicating concurrent in-flight requests
 * for the same key, and writing the resolved result into the cache only while
 * it is still the latest request for `key` (a newer forced request or an
 * invalidation in the meantime makes this response stale).
 *
 * @param key - Cache key from `buildQueryCacheKey`.
 * @param fetcher - Async function that resolves the fresh payload.
 * @param options - Optional `{ force, ttlMs }` settings.
 * @returns Resolved payload.
 */
export async function fetchWithCache<T>(
  key: string,
  fetcher: () => Promise<T>,
  options?: { force?: boolean; ttlMs?: number },
): Promise<T> {
  const active = Boolean(key) && _isCacheActive();
  if (!options?.force && active) {
    const cached = getCachedQuery<T>(key);
    if (cached !== null) {
      return cached;
    }
    const existing = inFlightRequests.get(key) as Promise<T> | undefined;
    if (existing) {
      return existing;
    }
  }

  const requestPromise: Promise<T> = Promise.resolve()
    .then(() => fetcher())
    .then((data) => {
      if (inFlightRequests.get(key) === requestPromise) {
        setCachedQuery(key, data, options?.ttlMs);
      }
      return data;
    })
    .finally(() => {
      if (inFlightRequests.get(key) === requestPromise) {
        inFlightRequests.delete(key);
      }
    });

  if (active) {
    inFlightRequests.set(key, requestPromise);
  }
  return requestPromise;
}

/** Evicts entries and forgets their in-flight requests in this tab only. */
function _invalidateLocal(matchToken?: string): void {
  if (!matchToken || !matchToken.trim()) {
    memoryCache.clear();
    inFlightRequests.clear();
    return;
  }
  const needle = matchToken.trim().toLowerCase();
  for (const key of Array.from(memoryCache.keys())) {
    if (key.includes(needle)) memoryCache.delete(key);
  }
  for (const key of Array.from(inFlightRequests.keys())) {
    if (key.includes(needle)) inFlightRequests.delete(key);
  }
}

/** Lazily opens the cross-tab channel (browser only); null when unsupported. */
function _getBroadcastChannel(): BroadcastChannel | null {
  if (broadcastChannel !== undefined) return broadcastChannel;
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") {
    broadcastChannel = null;
    return null;
  }
  try {
    const channel = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
    channel.onmessage = (event: MessageEvent<InvalidationMessage>) => {
      _invalidateLocal(event.data?.matchToken);
    };
    broadcastChannel = channel;
  } catch {
    broadcastChannel = null;
  }
  return broadcastChannel;
}

/**
 * Invalidates all cached queries, or only entries containing `matchToken`
 * (a tenant slug or a full key), in this tab and every other open tab.
 *
 * @param matchToken - Optional tenant slug or key substring to evict selectively.
 */
export function invalidateQueryCache(matchToken?: string): void {
  _invalidateLocal(matchToken);
  try {
    _getBroadcastChannel()?.postMessage({ matchToken } satisfies InvalidationMessage);
  } catch {
    // A closed channel only loses cross-tab freshness; local eviction already happened.
  }
}

/**
 * Number of live entries (test and diagnostics hook).
 *
 * @returns Current cache size.
 */
export function getQueryCacheSize(): number {
  return memoryCache.size;
}

/**
 * Test hook: explicitly enables or disables the in-memory cache inside Vitest
 * and clears existing entries.
 */
export function enableQueryCacheForTests(enabled: boolean): void {
  testOverrideEnabled = enabled;
  memoryCache.clear();
  inFlightRequests.clear();
  sessionIdentityByTenant.clear();
  lastSweepAt = 0;
}

/**
 * Clears the cache when another tab signs in as a different user (or signs
 * out), so this tab cannot keep serving the previous user's responses.
 */
function _handleStorage(event: StorageEvent): void {
  if (!event.key || !SESSION_STORAGE_KEY_PATTERN.test(event.key)) return;
  if (_userIdFromSession(event.oldValue) !== _userIdFromSession(event.newValue)) {
    _invalidateLocal();
  }
}

function _handleWalletUpdated(): void {
  invalidateQueryCache();
}

if (typeof window !== "undefined") {
  window.addEventListener("wallet-updated", _handleWalletUpdated);
  window.addEventListener("storage", _handleStorage);
}
