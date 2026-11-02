// frontend/src/components/auth/auth-guard.test.tsx
import { ApiError, UsersService, type UserRead } from "@/api_client";
import { TENANT_ACCESS_CHECK_EVENT } from "@/lib/api-config";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACCESS_RECHECK_MIN_INTERVAL_MS,
  AuthGuard,
  SERVER_UNREACHABLE_MESSAGE,
  isSignedOutError,
} from "./auth-guard";

const routeTo = (path: string) => path;

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo, tenantSlug: "logismart-test" }),
}));

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } }, error: null }),
    },
  }),
  clearStoredSession: vi.fn(),
  signOutAndRedirect: vi.fn(),
}));

const PROFILE = { id: "u1", email: "customerb2c@logismart.in", role: "customer" } as unknown as UserRead;

/** Builds the error the generated client throws for a refused `/users/me`. */
function apiError(status: number): ApiError {
  return new ApiError(
    { method: "GET", url: "/api/v1/users/me" },
    { url: "/api/v1/users/me", ok: false, status, statusText: "", body: { detail: "x" } },
    "refused",
  );
}

async function renderSignedIn() {
  render(
    <AuthGuard>
      <p>page content</p>
    </AuthGuard>,
  );
  await screen.findByText("page content");
}

describe("AuthGuard mid-session access re-check", () => {
  let now = 1_000_000;
  let profileSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    profileSpy = vi.spyOn(UsersService, "getMyProfile");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("swaps the page for the sign-out screen when a 403 re-check fails", async () => {
    profileSpy.mockResolvedValueOnce(PROFILE as never).mockRejectedValueOnce(apiError(403));
    await renderSignedIn();

    now += ACCESS_RECHECK_MIN_INTERVAL_MS;
    act(() => {
      window.dispatchEvent(new Event(TENANT_ACCESS_CHECK_EVENT));
    });

    expect(await screen.findByTestId("auth.access-denied")).toBeInTheDocument();
    expect(screen.getByTestId("auth.access-denied.sign-out")).toBeInTheDocument();
    expect(screen.queryByText("page content")).not.toBeInTheDocument();
  });

  it("re-checks on window focus too", async () => {
    profileSpy.mockResolvedValueOnce(PROFILE as never).mockRejectedValueOnce(apiError(403));
    await renderSignedIn();

    now += ACCESS_RECHECK_MIN_INTERVAL_MS;
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });

    expect(await screen.findByTestId("auth.access-denied")).toBeInTheDocument();
  });

  it("keeps the page when the re-check succeeds (role-based 403)", async () => {
    profileSpy.mockResolvedValue(PROFILE as never);
    await renderSignedIn();

    now += ACCESS_RECHECK_MIN_INTERVAL_MS;
    act(() => {
      window.dispatchEvent(new Event(TENANT_ACCESS_CHECK_EVENT));
    });

    await waitFor(() => expect(profileSpy).toHaveBeenCalledTimes(2));
    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(screen.queryByTestId("auth.access-denied")).not.toBeInTheDocument();
  });

  it("keeps the page on a transient (non 400/403) re-check failure", async () => {
    profileSpy.mockResolvedValueOnce(PROFILE as never).mockRejectedValueOnce(apiError(500));
    await renderSignedIn();

    now += ACCESS_RECHECK_MIN_INTERVAL_MS;
    act(() => {
      window.dispatchEvent(new Event(TENANT_ACCESS_CHECK_EVENT));
    });

    await waitFor(() => expect(profileSpy).toHaveBeenCalledTimes(2));
    expect(screen.getByText("page content")).toBeInTheDocument();
  });

  it("throttles bursts of 403s to one re-check per interval", async () => {
    profileSpy.mockResolvedValue(PROFILE as never);
    await renderSignedIn();

    now += ACCESS_RECHECK_MIN_INTERVAL_MS;
    act(() => {
      for (let i = 0; i < 5; i += 1) window.dispatchEvent(new Event(TENANT_ACCESS_CHECK_EVENT));
    });
    await waitFor(() => expect(profileSpy).toHaveBeenCalledTimes(2));
  });

  it("runs one trailing re-check for a 403 inside the throttle window", async () => {
    profileSpy.mockResolvedValueOnce(PROFILE as never).mockRejectedValueOnce(apiError(403));
    await renderSignedIn();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      act(() => {
        window.dispatchEvent(new Event(TENANT_ACCESS_CHECK_EVENT));
        window.dispatchEvent(new Event(TENANT_ACCESS_CHECK_EVENT));
      });
      expect(profileSpy).toHaveBeenCalledTimes(1);

      now += ACCESS_RECHECK_MIN_INTERVAL_MS;
      await act(async () => {
        vi.advanceTimersByTime(ACCESS_RECHECK_MIN_INTERVAL_MS);
      });
    } finally {
      vi.useRealTimers();
    }
    expect(await screen.findByTestId("auth.access-denied")).toBeInTheDocument();
    expect(profileSpy).toHaveBeenCalledTimes(2);
  });
});

describe("AuthGuard first load", () => {
  let profileSpy: ReturnType<typeof vi.spyOn>;
  const originalLocation = window.location;

  beforeEach(() => {
    profileSpy = vi.spyOn(UsersService, "getMyProfile");
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "http://localhost/logismart-test/ops", pathname: "/logismart-test/ops", search: "" },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  function renderGuard() {
    render(
      <AuthGuard>
        <p>page content</p>
      </AuthGuard>,
    );
  }

  it("keeps the session and shows a retry screen when /users/me answers 500", async () => {
    const { clearStoredSession } = await import("@/lib/supabase");
    profileSpy.mockRejectedValueOnce(apiError(500)).mockResolvedValueOnce(PROFILE as never);
    renderGuard();
    expect(await screen.findByTestId("auth.server-unreachable")).toHaveTextContent(SERVER_UNREACHABLE_MESSAGE);
    expect(clearStoredSession).not.toHaveBeenCalled();
    expect(window.location.href).toBe("http://localhost/logismart-test/ops");

    act(() => {
      screen.getByTestId("auth.server-unreachable.retry").click();
    });
    expect(await screen.findByText("page content")).toBeInTheDocument();
  });

  it("treats a network failure (no HTTP response) as transient too", async () => {
    profileSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderGuard();
    expect(await screen.findByTestId("auth.server-unreachable")).toBeInTheDocument();
  });

  it("signs out and redirects to login on 401", async () => {
    const { clearStoredSession } = await import("@/lib/supabase");
    profileSpy.mockRejectedValueOnce(apiError(401));
    renderGuard();
    await waitFor(() =>
      expect(window.location.href).toBe("/login?next=%2Flogismart-test%2Fops"),
    );
    expect(clearStoredSession).toHaveBeenCalledWith("logismart-test");
  });

  it("classifies only 401 / no session as signed out", () => {
    expect(isSignedOutError(apiError(401))).toBe(true);
    expect(isSignedOutError(apiError(500))).toBe(false);
    expect(isSignedOutError(apiError(503))).toBe(false);
    expect(isSignedOutError(new TypeError("Failed to fetch"))).toBe(false);
  });
});
