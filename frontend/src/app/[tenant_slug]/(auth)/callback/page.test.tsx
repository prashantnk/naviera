// frontend/src/app/[tenant_slug]/(auth)/callback/page.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PENDING_PASSWORD_RESET_KEY,
  savePendingPasswordReset,
} from "../login/login-form";
import AuthCallbackPage from "./page";

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({
    tenantSlug: "logismart-test",
    routeTo: (path: string) => `/logismart-test${path}`,
    tenant: { id: "t1", name: "Logismart Test", slug: "logismart-test", settings: {} },
  }),
}));

const routerPush = vi.fn();
const updateUser = vi.fn();
let currentSearchParams = new URLSearchParams("next=/wallet");
let currentSession: { access_token: string; user?: { email?: string } } | null = null;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
  useParams: () => ({ tenant_slug: "logismart-test" }),
  useSearchParams: () => currentSearchParams,
}));

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({
    auth: {
      getSession: async () => ({ data: { session: currentSession }, error: null }),
      updateUser: (args: unknown) => updateUser(args),
    },
  }),
}));

describe("AuthCallbackPage password-reset link persistence", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    routerPush.mockReset();
    updateUser.mockReset();
    window.sessionStorage.clear();
    currentSession = {
      access_token: "jwt-123",
      user: { email: "seller@logismart.in" },
    };
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "u1" }),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
  });

  it("applies the pending password from sessionStorage when the email link opens in the same tab", async () => {
    currentSearchParams = new URLSearchParams("intent=set_password&next=/wallet");
    savePendingPasswordReset("seller@logismart.in", "UpdatedSecret99");
    updateUser.mockResolvedValue({ data: {}, error: null });

    render(<AuthCallbackPage />);

    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith({ password: "UpdatedSecret99" })
    );
    expect(window.sessionStorage.getItem(PENDING_PASSWORD_RESET_KEY)).toBeNull();
    expect(routerPush).toHaveBeenCalledWith("/logismart-test/wallet");
  });

  it("prompts for a new password when the password-reset email link opens in a new tab (empty sessionStorage)", async () => {
    currentSearchParams = new URLSearchParams("intent=set_password&next=/wallet");
    updateUser.mockResolvedValue({ data: {}, error: null });

    render(<AuthCallbackPage />);

    const form = await screen.findByTestId("callback.set-password-form");
    expect(form).toBeInTheDocument();
    expect(routerPush).not.toHaveBeenCalled();

    // Reject passwords shorter than 8 characters
    fireEvent.change(screen.getByLabelText(/New password/), {
      target: { value: "short7" },
    });
    fireEvent.submit(form);
    expect(
      await screen.findByText("New password must be at least 8 characters.")
    ).toBeInTheDocument();
    expect(updateUser).not.toHaveBeenCalled();

    // Save a valid >= 8 character password and redirect to next
    fireEvent.change(screen.getByLabelText(/New password/), {
      target: { value: "NewTabPassword88" },
    });
    fireEvent.submit(form);

    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith({ password: "NewTabPassword88" })
    );
    expect(routerPush).toHaveBeenCalledWith("/logismart-test/wallet");
  });

  it("redirects without calling updateUser on a normal OTP or OAuth callback", async () => {
    currentSearchParams = new URLSearchParams("next=/shipments");

    render(<AuthCallbackPage />);

    await waitFor(() =>
      expect(routerPush).toHaveBeenCalledWith("/logismart-test/shipments")
    );
    expect(updateUser).not.toHaveBeenCalled();
  });
});
