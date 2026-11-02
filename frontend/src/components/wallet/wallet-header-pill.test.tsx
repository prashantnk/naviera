// frontend/src/components/wallet/wallet-header-pill.test.tsx
import { UserRole } from "@/api_client";
import { resolveCapabilities } from "@/components/auth/capabilities";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WalletHeaderPill } from "./wallet-header-pill";

const state: { role: UserRole; wallet: Record<string, unknown> | null } = {
  role: UserRole.CUSTOMER,
  wallet: null,
};

vi.mock("@/components/auth/auth-guard", () => ({
  useUser: () => ({ capabilities: resolveCapabilities(state.role) }),
}));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/t${path}`, tenantSlug: "t" }),
}));
vi.mock("@/components/providers/wallet-provider", () => ({
  useWallet: () => ({ wallet: state.wallet, refresh: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

describe("WalletHeaderPill (staff-finance #487)", () => {
  beforeEach(() => {
    state.role = UserRole.CUSTOMER;
    state.wallet = null;
  });

  it("shows an em dash, never ₹0.00, before GET /wallet resolves", () => {
    render(<WalletHeaderPill />);
    expect(screen.getByTestId("wallet.header.balance")).toHaveTextContent("—");
  });

  it("formats the balance with Indian grouping and shows Recharge to a customer", () => {
    state.wallet = { balance: 27732.63, summary: { pending_recharge: 666 } };
    render(<WalletHeaderPill />);
    expect(screen.getByTestId("wallet.header.balance")).toHaveTextContent("₹27,732.63");
    expect(screen.getByText(/\+₹666\.00 Pending/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Recharge Wallet/i })).toBeInTheDocument();
  });

  it.each([UserRole.READ_ONLY_USER, UserRole.SUPPORT_USER])(
    "is hidden for %s (no wallet of their own)",
    (role) => {
      state.role = role;
      state.wallet = { balance: 0, summary: {} };
      const { container } = render(<WalletHeaderPill />);
      expect(container).toBeEmptyDOMElement();
    }
  );

  it.each([UserRole.OWNER, UserRole.ADMIN, UserRole.OPERATIONS_USER])(
    "renders a clean 'Wallet & Ledger' link pill without ₹0.00 balance or Recharge button for staff (%s)",
    (role) => {
      state.role = role;
      state.wallet = { balance: 0, summary: {} };
      render(<WalletHeaderPill />);
      const pill = screen.getByTestId("wallet.header.pill");
      expect(pill).toBeInTheDocument();
      expect(pill).toHaveTextContent("Wallet & Ledger");
      expect(screen.queryByTestId("wallet.header.balance")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Recharge Wallet/i })).not.toBeInTheDocument();
    },
  );
});
