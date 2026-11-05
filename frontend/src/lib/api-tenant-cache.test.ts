// frontend/src/lib/api-tenant-cache.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { shouldInvalidateAfterRequest } from "./api-config";
import {
  getTenantBySlug,
  getTenantMemoryCacheSize,
  invalidateTenantMemoryCache,
  MAX_TENANT_CACHE_ENTRIES,
} from "./api";

vi.mock("./supabase", () => ({
  clearStoredSession: vi.fn(),
  getSupabaseClient: vi.fn(),
}));

/** Minimal `fetch` response. */
function response(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("getTenantBySlug server memory cache", () => {
  beforeEach(() => {
    invalidateTenantMemoryCache();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("stays bounded when random unknown slugs are requested", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => response(404));
    for (let i = 0; i < MAX_TENANT_CACHE_ENTRIES * 3; i += 1) {
      await expect(getTenantBySlug(`random-${i}`)).resolves.toBeNull();
    }
    expect(getTenantMemoryCacheSize()).toBe(MAX_TENANT_CACHE_ENTRIES);
  });

  it("serves a hit from memory, expires it after the short TTL, and honours invalidation", async () => {
    vi.useFakeTimers();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => response(200, { slug: "logismart-test", name: "v1" }));

    await getTenantBySlug("logismart-test");
    await getTenantBySlug("Logismart-Test");
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(15_001);
    await getTenantBySlug("logismart-test");
    expect(fetchSpy).toHaveBeenCalledTimes(2);

    invalidateTenantMemoryCache("logismart-test");
    await getTenantBySlug("logismart-test");
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("never caches a server error", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(async () => response(500))
      .mockImplementationOnce(async () => response(200, { slug: "naviera" }));
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(getTenantBySlug("naviera")).rejects.toThrow("Server Error: 500");
    await expect(getTenantBySlug("naviera")).resolves.toEqual({ slug: "naviera" });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});

describe("shouldInvalidateAfterRequest", () => {
  it.each([
    ["POST", "/api/v1/manifests", 201],
    ["PATCH", "/api/v1/tenants/settings", 200],
    ["DELETE", "/api/v1/addresses/a1", 204],
    ["POST", "/api/v1/manifests/m1/dispatch", 500],
    ["POST", "/api/v1/shipments", undefined],
  ])("evicts after %s %s (status %s)", (method, url, status) => {
    expect(shouldInvalidateAfterRequest(method, url, status)).toBe(true);
  });

  it.each([
    ["GET", "/api/v1/shipments", 200],
    ["post", "/api/v1/quotes", 200],
    ["POST", "http://localhost:3000/api/v1/shipments/valuation?x=1", 200],
    ["POST", "/api/v1/shipments/s1/reprice-preview", 200],
    ["POST", "/api/v1/manifests", 422],
    ["PUT", "/api/v1/users/u1", 403],
    [undefined, "/api/v1/manifests", 200],
  ])("keeps the cache after %s %s (status %s)", (method, url, status) => {
    expect(shouldInvalidateAfterRequest(method, url, status)).toBe(false);
  });
});
