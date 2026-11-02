// frontend/src/lib/api-config.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AUTH_ENDPOINT_PREFIX,
  PROFILE_ENDPOINT_PATH,
  TENANT_ACCESS_CHECK_EVENT,
  buildLoginRedirectUrl,
  notifyTenantAccessCheck,
  redirectToLoginOnUnauthorized,
  resetUnauthorizedRedirectStateForTests,
} from "./api-config";
import { clearStoredSession } from "./supabase";

vi.mock("./supabase", () => ({
  clearStoredSession: vi.fn(),
  getSupabaseClient: vi.fn(),
}));

describe("notifyTenantAccessCheck", () => {
  const listener = vi.fn();

  afterEach(() => {
    window.removeEventListener(TENANT_ACCESS_CHECK_EVENT, listener);
    listener.mockReset();
  });

  it("fires the re-check event for a 403 on a normal endpoint", () => {
    window.addEventListener(TENANT_ACCESS_CHECK_EVENT, listener);
    expect(notifyTenantAccessCheck(403, "/api/v1/shipments/calculate-rates")).toBe(true);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it.each([400, 401, 404, 422, 500, undefined])("ignores status %s", (status) => {
    window.addEventListener(TENANT_ACCESS_CHECK_EVENT, listener);
    expect(notifyTenantAccessCheck(status, "/api/v1/wallet")).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });

  it("never fires for the profile endpoint itself (no re-check loop)", () => {
    window.addEventListener(TENANT_ACCESS_CHECK_EVENT, listener);
    expect(notifyTenantAccessCheck(403, PROFILE_ENDPOINT_PATH)).toBe(false);
    expect(notifyTenantAccessCheck(403, `${PROFILE_ENDPOINT_PATH}?x=1`)).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("buildLoginRedirectUrl (F-07)", () => {
  it("keeps the tenant prefix on path routing and preserves the current page", () => {
    expect(buildLoginRedirectUrl("logismart-test", "/logismart-test/shipments", "?page=2")).toBe(
      `/logismart-test/login?next=${encodeURIComponent("/logismart-test/shipments?page=2")}`,
    );
  });

  it("uses /login on a subdomain or custom domain", () => {
    expect(buildLoginRedirectUrl("logismart", "/wallet", "")).toBe(
      `/login?next=${encodeURIComponent("/wallet")}`,
    );
  });

  it("does not redirect from the login page itself", () => {
    expect(buildLoginRedirectUrl("logismart-test", "/logismart-test/login", "")).toBeNull();
    expect(buildLoginRedirectUrl("logismart", "/login", "?next=/x")).toBeNull();
  });
});

describe("redirectToLoginOnUnauthorized (F-07)", () => {
  const navigate = vi.fn();

  beforeEach(() => {
    navigate.mockReset();
    vi.mocked(clearStoredSession).mockReset();
    resetUnauthorizedRedirectStateForTests("naviera");
    window.history.pushState({}, "", "/naviera/shipments/abc?tab=charges");
  });

  it("clears the session and sends a signed-in 401 to /login?next=", () => {
    expect(redirectToLoginOnUnauthorized(401, "/api/v1/shipments", true, navigate)).toBe(true);
    expect(clearStoredSession).toHaveBeenCalledWith("naviera");
    expect(navigate).toHaveBeenCalledWith(
      `/naviera/login?next=${encodeURIComponent("/naviera/shipments/abc?tab=charges")}`,
    );
  });

  it("navigates only once for parallel 401s", () => {
    redirectToLoginOnUnauthorized(401, "/api/v1/shipments", true, navigate);
    expect(redirectToLoginOnUnauthorized(401, "/api/v1/wallet", true, navigate)).toBe(false);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["a non-401 status", 403, "/api/v1/shipments", true],
    ["a wrong-password login", 401, `${AUTH_ENDPOINT_PREFIX}login`, true],
    ["a request sent without a token", 401, "/api/v1/tracking/NAV-1", false],
  ])("ignores %s", (_label, status, url, sentToken) => {
    expect(redirectToLoginOnUnauthorized(status, url, sentToken, navigate)).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("does nothing before a tenant is configured", () => {
    resetUnauthorizedRedirectStateForTests(null);
    expect(redirectToLoginOnUnauthorized(401, "/api/v1/shipments", true, navigate)).toBe(false);
  });
});
