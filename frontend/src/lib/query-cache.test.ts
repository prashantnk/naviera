// frontend/src/lib/query-cache.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildQueryCacheKey,
  enableQueryCacheForTests,
  fetchWithCache,
  getCachedQuery,
  hasCachedQuery,
  getQueryCacheSize,
  invalidateQueryCache,
  MAX_QUERY_CACHE_ENTRIES,
  setCachedQuery,
} from "./query-cache";

/** A promise plus its resolver, for controlling when a fake request settles. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** Stores a minimal Supabase session for `userId` the way supabase-js / login-form do. */
function signIn(tenantSlug: string, userId: string): void {
  window.localStorage.setItem(
    `sb-${tenantSlug}-auth-token`,
    JSON.stringify({ access_token: "jwt", user: { id: userId } }),
  );
}

describe("query-cache (SWR client memory cache)", () => {
  beforeEach(() => {
    enableQueryCacheForTests(true);
  });

  afterEach(() => {
    enableQueryCacheForTests(false);
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it("builds deterministic keys regardless of parameter property order", () => {
    const keyA = buildQueryCacheKey("Logismart-Test", "u-1", "shipments", {
      page: 1,
      isB2B: false,
      direction: "ALL",
    });
    const keyB = buildQueryCacheKey("logismart-test", "u-1", "shipments", {
      direction: "ALL",
      isB2B: false,
      page: 1,
    });
    expect(keyA).toBe(keyB);
    expect(keyA).toBe(
      'logismart-test::anon::u-1::shipments::direction="ALL"&isB2B=false&page=1',
    );
  });

  it("stores and retrieves typed responses until TTL expiry", () => {
    vi.useFakeTimers();
    const key = buildQueryCacheKey("logismart-test", "u-1", "dashboard", {
      days: 30,
    });
    expect(hasCachedQuery(key)).toBe(false);

    setCachedQuery(key, { delivered: 42 }, 5_000);
    expect(hasCachedQuery(key)).toBe(true);
    expect(getCachedQuery<{ delivered: number }>(key)).toEqual({
      delivered: 42,
    });

    vi.advanceTimersByTime(5_001);
    expect(hasCachedQuery(key)).toBe(false);
    expect(getCachedQuery(key)).toBeNull();
  });

  it("isolates cache entries by tenant and user scope and supports selective invalidation", () => {
    const k1 = buildQueryCacheKey("logismart-test", "u-1", "wallet");
    const k2 = buildQueryCacheKey("logismart", "u-1", "wallet");
    setCachedQuery(k1, "test-tenant-wallet");
    setCachedQuery(k2, "prod-tenant-wallet");

    invalidateQueryCache("logismart-test");
    expect(getCachedQuery(k1)).toBeNull();
    expect(getCachedQuery(k2)).toBe("prod-tenant-wallet");

    invalidateQueryCache();
    expect(getCachedQuery(k2)).toBeNull();
  });

  it("automatically invalidates on the global wallet-updated event", () => {
    const key = buildQueryCacheKey("logismart-test", "u-1", "wallet");
    setCachedQuery(key, { balance: 500 });
    expect(hasCachedQuery(key)).toBe(true);

    window.dispatchEvent(new Event("wallet-updated"));
    expect(hasCachedQuery(key)).toBe(false);
  });

  it("deduplicates concurrent in-flight requests via fetchWithCache", async () => {
    const key = buildQueryCacheKey("logismart-test", "session", "manifests");
    const fetcher = vi.fn().mockResolvedValue(["pur-1", "pur-2"]);

    const [r1, r2] = await Promise.all([
      fetchWithCache(key, fetcher),
      fetchWithCache(key, fetcher),
    ]);

    expect(r1).toEqual(["pur-1", "pur-2"]);
    expect(r2).toEqual(["pur-1", "pur-2"]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(getCachedQuery(key)).toEqual(["pur-1", "pur-2"]);
  });
  it("scopes keys by the signed-in user so another user never reads them", () => {
    signIn("logismart-test", "user-owner");
    const ownerKey = buildQueryCacheKey("logismart-test", "session", "wallet-overview");
    setCachedQuery(ownerKey, { balance: 900 });
    expect(ownerKey).toContain("::user-owner::");

    // Same tab: sign out, then sign in as a customer without a page reload.
    signIn("logismart-test", "user-customer");
    const customerKey = buildQueryCacheKey("logismart-test", "session", "wallet-overview");
    expect(customerKey).not.toBe(ownerKey);
    expect(getCachedQuery(customerKey)).toBeNull();

    window.localStorage.removeItem("sb-logismart-test-auth-token");
    expect(buildQueryCacheKey("logismart-test", "session", "wallet-overview")).toContain("::anon::");
  });

  it("clears everything when another tab switches the signed-in user", () => {
    signIn("logismart-test", "user-owner");
    const key = buildQueryCacheKey("logismart-test", "session", "shipments-list");
    setCachedQuery(key, ["owner-row"]);

    const sessionKey = "sb-logismart-test-auth-token";
    const ownerSession = window.localStorage.getItem(sessionKey);
    // Token refresh for the same user keeps the cache.
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: sessionKey,
        oldValue: ownerSession,
        newValue: JSON.stringify({ access_token: "refreshed", user: { id: "user-owner" } }),
      }),
    );
    expect(getCachedQuery(key)).toEqual(["owner-row"]);

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: sessionKey,
        oldValue: ownerSession,
        newValue: JSON.stringify({ access_token: "jwt", user: { id: "user-customer" } }),
      }),
    );
    expect(getCachedQuery(key)).toBeNull();
  });

  it("is bounded: evicts the least recently used entry beyond the cap", () => {
    const keyFor = (i: number) => buildQueryCacheKey("logismart-test", "session", "search", { q: i });
    for (let i = 0; i < MAX_QUERY_CACHE_ENTRIES; i += 1) {
      setCachedQuery(keyFor(i), i);
    }
    // Touch entry 0 so entry 1 becomes the least recently used.
    expect(getCachedQuery(keyFor(0))).toBe(0);
    setCachedQuery(keyFor(MAX_QUERY_CACHE_ENTRIES), MAX_QUERY_CACHE_ENTRIES);

    expect(getQueryCacheSize()).toBe(MAX_QUERY_CACHE_ENTRIES);
    expect(getCachedQuery(keyFor(0))).toBe(0);
    expect(getCachedQuery(keyFor(1))).toBeNull();

    for (let i = 0; i < 5 * MAX_QUERY_CACHE_ENTRIES; i += 1) {
      setCachedQuery(keyFor(1000 + i), i);
    }
    expect(getQueryCacheSize()).toBe(MAX_QUERY_CACHE_ENTRIES);
  });

  it("sweeps expired entries even if they are never read again", () => {
    vi.useFakeTimers();
    for (let i = 0; i < 10; i += 1) {
      setCachedQuery(buildQueryCacheKey("logismart-test", "session", "old", { i }), i, 1_000);
    }
    expect(getQueryCacheSize()).toBe(10);
    vi.advanceTimersByTime(31_000);
    setCachedQuery(buildQueryCacheKey("logismart-test", "session", "fresh"), "x");
    expect(getQueryCacheSize()).toBe(1);
  });

  it("does not cache a response that started before an invalidation (mutation race)", async () => {
    const key = buildQueryCacheKey("logismart-test", "session", "manifests-list");
    const staleResponse = deferred<string[]>();
    const stale = fetchWithCache(key, () => staleResponse.promise);

    invalidateQueryCache(); // e.g. "Create pickup request" POST succeeded meanwhile
    staleResponse.resolve(["before-mutation"]);

    await expect(stale).resolves.toEqual(["before-mutation"]);
    expect(getCachedQuery(key)).toBeNull();
  });

  it("cleans up in-flight dedup entries on error so the next call retries", async () => {
    const key = buildQueryCacheKey("logismart-test", "session", "addresses");
    const fetcher = vi
      .fn<() => Promise<string[]>>()
      .mockRejectedValueOnce(new Error("502"))
      .mockResolvedValueOnce(["warehouse"]);

    await expect(fetchWithCache(key, fetcher)).rejects.toThrow("502");
    await expect(fetchWithCache(key, fetcher)).resolves.toEqual(["warehouse"]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("keeps a newer forced request deduplicated when an older one settles", async () => {
    const key = buildQueryCacheKey("logismart-test", "session", "wallet");
    const oldResponse = deferred<string>();
    const newResponse = deferred<string>();
    const old = fetchWithCache(key, () => oldResponse.promise);
    const fresh = fetchWithCache(key, () => newResponse.promise, { force: true });
    oldResponse.resolve("old");
    await old;
    const joiner = vi.fn().mockResolvedValue("third");
    const joined = fetchWithCache(key, joiner);
    newResponse.resolve("new");
    await expect(fresh).resolves.toBe("new");
    await expect(joined).resolves.toBe("new");
    expect(joiner).not.toHaveBeenCalled();
  });

  it("broadcasts invalidations to other tabs and applies theirs", () => {
    const posted: unknown[] = [];
    let onmessage: ((event: MessageEvent) => void) | null = null;
    class FakeChannel {
      constructor(public name: string) {}
      postMessage(message: unknown) {
        posted.push(message);
      }
      set onmessage(handler: (event: MessageEvent) => void) {
        onmessage = handler;
      }
    }
    vi.stubGlobal("BroadcastChannel", FakeChannel);
    vi.resetModules();
    return import("./query-cache").then((fresh) => {
      fresh.enableQueryCacheForTests(true);
      const key = fresh.buildQueryCacheKey("logismart-test", "session", "invoices");
      fresh.setCachedQuery(key, ["inv-1"]);
      fresh.invalidateQueryCache();
      expect(posted).toEqual([{ matchToken: undefined }]);

      fresh.setCachedQuery(key, ["inv-2"]);
      onmessage?.(new MessageEvent("message", { data: {} }));
      expect(fresh.getCachedQuery(key)).toBeNull();
      fresh.enableQueryCacheForTests(false);
      vi.unstubAllGlobals();
    });
  });

  it("is disabled when no window exists (server render)", async () => {
    vi.stubGlobal("window", undefined);
    try {
      const key = "logismart-test::anon::session::wallet::";
      setCachedQuery(key, "leak");
      expect(getCachedQuery(key)).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
