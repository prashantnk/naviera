// frontend/src/components/auth/admin-only-guard.test.tsx
import { UserRole } from "@/api_client";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EditB2BShipmentLayout from "@/app/[tenant_slug]/(app)/b2b/shipments/[id]/edit/layout";
import EditShipmentLayout from "@/app/[tenant_slug]/(app)/shipments/[id]/edit/layout";
import { resolveCapabilities } from "./capabilities";

const state: { role: UserRole } = { role: UserRole.CUSTOMER };

vi.mock("@/components/auth/auth-guard", () => ({
  useUser: () => ({ capabilities: resolveCapabilities(state.role) }),
}));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/t${path}` }),
}));

function rendersEditForm(
  Layout: (p: { children: React.ReactNode }) => React.ReactNode,
  role: UserRole,
): boolean {
  state.role = role;
  const { unmount } = render(<Layout>{<p>edit-shipment-form</p>}</Layout>);
  const shown = screen.queryByText("edit-shipment-form") !== null;
  if (!shown) {
    expect(screen.getByText(/isn't available for your role/i)).toBeInTheDocument();
  }
  unmount();
  return shown;
}

describe("shipment edit route guard (AdminOnlyGuard)", () => {
  it("allows customers (own live orders, B9) and operators, blocks support and read-only staff", () => {
    const allowed = new Set<UserRole>([
      UserRole.CUSTOMER,
      UserRole.OWNER,
      UserRole.ADMIN,
      UserRole.OPERATIONS_USER,
    ]);
    for (const Layout of [EditShipmentLayout, EditB2BShipmentLayout]) {
      for (const role of Object.values(UserRole)) {
        expect(rendersEditForm(Layout, role)).toBe(allowed.has(role));
      }
    }
  });
});
