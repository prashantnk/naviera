// frontend/src/components/wallet/wallet-header-pill.test.tsx
import { UserRole } from "@/api_client";
import { resolveCapabilities } from "@/components/auth/capabilities";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WalletHeaderPill, WalletRechargeDialog } from "./wallet-header-pill";

const mockCreateIntent = vi.fn();
const mockConfirmUpi = vi.fn();

const state: { role: UserRole; wallet: Record<string, unknown> | null } = {
  role: UserRole.CUSTOMER,
  wallet: null,
};

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    WalletService: {
      createUpiRechargeIntent: (...args: unknown[]) => mockCreateIntent(...args),
      confirmUpiRecharge: (...args: unknown[]) => mockConfirmUpi(...args),
      getUpiRechargeStatus: vi.fn().mockResolvedValue({ status: "PENDING" }),
    },
  };
});
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

describe("WalletRechargeDialog — click acknowledgement (rel8)", () => {
  beforeEach(() => {
    state.role = UserRole.CUSTOMER;
    state.wallet = { balance: 0, summary: {}, wallet_config: { merchant_vpa: "shop@upi" } };
    mockCreateIntent.mockReset();
    mockConfirmUpi.mockReset();
    vi.mocked(toast.success).mockClear();
    mockCreateIntent.mockResolvedValue({
      transaction_id: "txn-9",
      amount: 1000,
      qr_svg_data_url: "data:image/svg+xml,",
      merchant_name: "Shop",
      merchant_vpa: "shop@upi",
      upi_uri: null,
    });
  });

  it("I Have Paid spins, disables, and submits the UTR exactly once on a double click", async () => {
    let resolveConfirm: (value: { balance: number }) => void = () => {};
    mockConfirmUpi.mockReturnValue(
      new Promise((resolve) => {
        resolveConfirm = resolve;
      })
    );
    const onOpenChange = vi.fn();
    render(<WalletRechargeDialog open onOpenChange={onOpenChange} />);

    fireEvent.click(screen.getByRole("button", { name: /Generate UPI QR/i }));
    fireEvent.change(await screen.findByTestId("wallet.recharge.utr-input"), {
      target: { value: "640721641527" },
    });
    const paid = screen.getByRole("button", { name: /I Have Paid/i });
    fireEvent.click(paid);
    fireEvent.click(paid);

    expect(paid).toBeDisabled();
    expect(paid.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.getByRole("button", { name: /Change Amount/i })).toBeDisabled();
    expect(mockConfirmUpi).toHaveBeenCalledTimes(1);
    expect(mockConfirmUpi).toHaveBeenCalledWith("txn-9", "t", { utr_number: "640721641527" });

    resolveConfirm({ balance: 0 });
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mockConfirmUpi).toHaveBeenCalledTimes(1);
  });
});
