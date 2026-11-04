// frontend/src/lib/query-cache.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildQueryCacheKey,
  enableQueryCacheForTests,
  getCachedQuery,
  hasCachedQuery,
  invalidateQueryCache,
  setCachedQuery,
} from "./query-cache";

describe("query-cache (SWR client memory cache)", () => {
  beforeEach(() => {
    enableQueryCacheForTests(true);
  });

  afterEach(() => {
    enableQueryCacheForTests(false);
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
      'logismart-test::u-1::shipments::direction="ALL"&isB2B=false&page=1',
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
});
