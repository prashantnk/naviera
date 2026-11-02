// frontend/src/components/auth/capability-guard.test.tsx
import { UserRole } from "@/api_client";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import FinancesLayout from "@/app/[tenant_slug]/(app)/finances/layout";
import B2BPickupNewLayout from "@/app/[tenant_slug]/(app)/b2b/pickup-requests/new/layout";
import B2BShipmentsNewLayout from "@/app/[tenant_slug]/(app)/b2b/shipments/new/layout";
import PickupNewLayout from "@/app/[tenant_slug]/(app)/pickup-requests/new/layout";
import ShipmentsNewLayout from "@/app/[tenant_slug]/(app)/shipments/new/layout";
import WalletLayout from "@/app/[tenant_slug]/(app)/wallet/layout";
import { resolveCapabilities } from "./capabilities";

const state: { role: UserRole } = { role: UserRole.CUSTOMER };

vi.mock("@/components/auth/auth-guard", () => ({
  useUser: () => ({ capabilities: resolveCapabilities(state.role) }),
}));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/t${path}` }),
}));

/** Renders a layout around a marker child and reports whether the child is shown. */
function rendersChild(Layout: (p: { children: React.ReactNode }) => React.ReactNode, role: UserRole): boolean {
  state.role = role;
  const { unmount } = render(<Layout>{<p>page-content</p>}</Layout>);
  const shown = screen.queryByText("page-content") !== null;
  if (!shown) {
    expect(screen.getByTestId("capability-guard.blocked")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go to Home/i })).toHaveAttribute("href", "/t/dashboard");
  }
  unmount();
  return shown;
}

describe("finance route guards (no raw 403 pages for staff)", () => {
  it("/finances/* is open to customers, owner, admin and read-only only", () => {
    expect(rendersChild(FinancesLayout, UserRole.CUSTOMER)).toBe(true);
    expect(rendersChild(FinancesLayout, UserRole.OWNER)).toBe(true);
    expect(rendersChild(FinancesLayout, UserRole.ADMIN)).toBe(true);
    expect(rendersChild(FinancesLayout, UserRole.READ_ONLY_USER)).toBe(true);
    expect(rendersChild(FinancesLayout, UserRole.OPERATIONS_USER)).toBe(false);
    expect(rendersChild(FinancesLayout, UserRole.SUPPORT_USER)).toBe(false);
  });

  it("/wallet is blocked only for support users", () => {
    for (const role of Object.values(UserRole)) {
      expect(rendersChild(WalletLayout, role)).toBe(role !== UserRole.SUPPORT_USER);
    }
  });

  it("booking URLs are blocked for read-only and support users in both flows", () => {
    const bookers = new Set<UserRole>([
      UserRole.CUSTOMER,
      UserRole.OWNER,
      UserRole.ADMIN,
      UserRole.OPERATIONS_USER,
    ]);
    for (const Layout of [ShipmentsNewLayout, PickupNewLayout, B2BShipmentsNewLayout, B2BPickupNewLayout]) {
      for (const role of Object.values(UserRole)) {
        expect(rendersChild(Layout, role)).toBe(bookers.has(role));
      }
    }
  });
});
