// frontend/src/components/blocks/header.test.tsx
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Header } from "./header";

const clearStoredSession = vi.fn();

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({
    auth: { getSession: async () => ({ data: { session: { access_token: "jwt" } } }) },
  }),
  clearStoredSession: (slug: string) => clearStoredSession(slug),
  signOutAndRedirect: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenant_slug: "logismart-test" }),
  usePathname: () => "/logismart-test",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({
    tenant: { id: "t1", name: "Logismart Test", slug: "logismart-test", settings: {} },
    routeTo: (path: string) => `/logismart-test${path}`,
  }),
}));

describe("marketing Header", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    clearStoredSession.mockReset();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("keeps the stored session when /users/me fails with a 5xx", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 503 });
    render(<Header />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(clearStoredSession).not.toHaveBeenCalled();
  });

  it("clears the stored session when the token is rejected (401)", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 401 });
    render(<Header />);
    await waitFor(() => expect(clearStoredSession).toHaveBeenCalledWith("logismart-test"));
  });

  it("labels the mobile menu toggle and reports its expanded state", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 503 });
    render(<Header />);
    await act(async () => {}); // let the session check settle
    const toggle = screen.getByTestId("header.mobile-menu-toggle");
    expect(toggle).toHaveAttribute("aria-label", "Open menu");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-label", "Close menu");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
