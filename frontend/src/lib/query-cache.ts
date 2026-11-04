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
 *    never shown after an action.
 */

export const DEFAULT_QUERY_CACHE_TTL_MS = 60_000;

interface CacheEntry<T = unknown> {
  data: T;
  expiresAt: number;
}

const memoryCache = new Map<string, CacheEntry>();
const inFlightRequests = new Map<string, Promise<unknown>>();

let testOverrideEnabled = false;

function _isCacheActive(): boolean {
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
 * Builds a deterministic, tenant- and user-scoped cache key.
 *
 * @param tenantSlug - Active tenant slug (`logismart`, `logismart-test`, ...).
 * @param scopeKey - User or role scope (`user.id`, `staff`, `customer`, ...).
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
  const cleanTenant = (tenantSlug || "default").trim().toLowerCase();
  const cleanScope = (scopeKey || "anon").trim().toLowerCase();
  const cleanEndpoint = endpoint.trim().toLowerCase();
  return `${cleanTenant}::${cleanScope}::${cleanEndpoint}::${_stableSerialize(params)}`;
}

/**
 * Reads a non-expired cached response synchronously.
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
 * Stores a response in the in-memory SWR cache.
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
  memoryCache.set(key, {
    data,
    expiresAt: Date.now() + ttlMs,
  });
  return data;
}

/**
 * Fetches data using `fetcher`, returning cached data immediately when warm
 * (unless `options.force` is true), deduplicating concurrent in-flight requests
 * for the same key, and writing the resolved result into the cache.
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
  if (!options?.force) {
    const cached = getCachedQuery<T>(key);
    if (cached !== null) {
      return cached;
    }
    if (key && _isCacheActive()) {
      const existing = inFlightRequests.get(key) as Promise<T> | undefined;
      if (existing) {
        return existing;
      }
    }
  }

  const requestPromise = Promise.resolve()
    .then(() => fetcher())
    .then((data) => {
      setCachedQuery(key, data, options?.ttlMs);
      return data;
    })
    .finally(() => {
      inFlightRequests.delete(key);
    });

  if (key && _isCacheActive()) {
    inFlightRequests.set(key, requestPromise);
  }
  return requestPromise;
}

/**
 * Invalidates all cached queries, or only entries matching a tenant/prefix token.
 *
 * @param matchToken - Optional tenant slug or key substring to evict selectively.
 */
export function invalidateQueryCache(matchToken?: string): void {
  if (!matchToken || !matchToken.trim()) {
    memoryCache.clear();
    inFlightRequests.clear();
    return;
  }
  const needle = matchToken.trim().toLowerCase();
  for (const key of Array.from(memoryCache.keys())) {
    if (key.startsWith(`${needle}::`) || key.includes(needle)) {
      memoryCache.delete(key);
    }
  }
  for (const key of Array.from(inFlightRequests.keys())) {
    if (key.startsWith(`${needle}::`) || key.includes(needle)) {
      inFlightRequests.delete(key);
    }
  }
}

/**
 * Test hook: explicitly enables or disables the in-memory cache inside Vitest
 * and clears existing entries.
 */
export function enableQueryCacheForTests(enabled: boolean): void {
  testOverrideEnabled = enabled;
  memoryCache.clear();
  inFlightRequests.clear();
}

if (typeof window !== "undefined") {
  window.addEventListener("wallet-updated", () => {
    invalidateQueryCache();
  });
}
