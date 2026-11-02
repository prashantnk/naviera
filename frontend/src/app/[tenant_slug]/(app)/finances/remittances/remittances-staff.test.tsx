// frontend/src/app/[tenant_slug]/(app)/finances/remittances/remittances-staff.test.tsx
import { UserRole } from "@/api_client";
import { resolveCapabilities } from "@/components/auth/capabilities";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RemittancesListPage from "./page";

const mockListRemittances = vi.fn();
const state: { role: UserRole } = { role: UserRole.OWNER };

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    RemittancesService: {
      listRemittances: (...args: unknown[]) => mockListRemittances(...args),
      previewPendingRemittance: vi.fn(),
      createRemittance: vi.fn(),
    },
    UsersService: { listUsersInTenant: vi.fn().mockResolvedValue([]) },
  };
});
vi.mock("@/components/auth/auth-guard", () => ({
  useUser: () => ({ capabilities: resolveCapabilities(state.role) }),
}));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/t${path}`, tenantSlug: "t" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ROW = {
  id: "r-1",
  tenant_id: "t-1",
  merchant_user_id: "m-1",
  merchant_email: "seller@shop.in",
  remittance_number: "R4713782026110100001",
  processed_date: "2026-11-01",
  bank_utr: "AXISP00847542539",
  state: "Completed",
  total_remittance: 1234.5,
  total_orders: 1,
  shipment_breakdown: [],
  created_at: "2026-11-01T05:00:00",
};

describe("Remittances list — staff view", () => {
  beforeEach(() => {
    mockListRemittances.mockReset();
    mockListRemittances.mockResolvedValue([ROW]);
  });

  it("names the merchant on each row and offers batch processing to an Owner", async () => {
    state.role = UserRole.OWNER;
    render(<RemittancesListPage />);
    expect(await screen.findByTestId(`remittances.row.${ROW.remittance_number}.merchant`)).toHaveTextContent(
      "seller@shop.in"
    );
    expect(screen.getByRole("button", { name: /Process Remittance Batch/i })).toBeInTheDocument();
  });

  it("read-only staff see the merchant column but no write button", async () => {
    state.role = UserRole.READ_ONLY_USER;
    render(<RemittancesListPage />);
    expect(await screen.findByText("MERCHANT")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Process Remittance Batch/i })).not.toBeInTheDocument();
  });

  it("customers keep the Delhivery merchant layout (no merchant column, no batch button)", async () => {
    state.role = UserRole.CUSTOMER;
    render(<RemittancesListPage />);
    await screen.findAllByText(ROW.remittance_number);
    expect(screen.queryByText("MERCHANT")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Process Remittance Batch/i })).not.toBeInTheDocument();
  });
});
