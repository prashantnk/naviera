// frontend/src/app/[tenant_slug]/(app)/wallet/wallet-staff.test.tsx
import { UserRole, WalletTxnStatus, WalletTxnType } from "@/api_client";
import { resolveCapabilities } from "@/components/auth/capabilities";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UnifiedWalletPage from "./page";

const mockList = vi.fn();
const mockPending = vi.fn();
const mockApprove = vi.fn();
const mockOfflineCredit = vi.fn();
const state: { role: UserRole } = { role: UserRole.READ_ONLY_USER };

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    WalletService: {
      listWalletTransactions: (...args: unknown[]) => mockList(...args),
      listTenantPendingRecharges: (...args: unknown[]) => mockPending(...args),
      approvePendingRecharge: (...args: unknown[]) => mockApprove(...args),
      recordAdminOfflineWalletCredit: (...args: unknown[]) => mockOfflineCredit(...args),
    },
  };
});
vi.mock("@/components/auth/auth-guard", () => ({
  useUser: () => ({
    user: { id: "u-staff", email: "staff@logismart.in", role: state.role },
    canAccessB2B: true,
    capabilities: resolveCapabilities(state.role),
  }),
}));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/t${path}`, tenantSlug: "t" }),
}));
vi.mock("@/components/providers/wallet-provider", () => ({
  useWallet: () => ({
    wallet: { balance: 0, summary: { pending_recharge: 0, total_spent: 0, total_refunded: 0, collectible_cod: 0 } },
    refresh: vi.fn(),
  }),
}));
vi.mock("@/lib/api", () => ({ downloadWalletLedgerCsv: vi.fn(), downloadWalletReceiptPdf: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const PENDING = {
  id: "txn-1",
  wallet_id: "w-1",
  tenant_id: "t-1",
  user_id: "u-cust",
  user_email: "customerb2c@logismart.in",
  txn_type: WalletTxnType.RECHARGE,
  service_category: "RECHARGE",
  opening_balance: 100,
  amount: 333,
  closing_balance: 100,
  utr_number: "640721641527",
  receipt_number: "REC-2627-5BE668A8",
  status: WalletTxnStatus.PENDING,
  created_at: "2026-11-01T05:00:00",
  direction: "CREDIT",
};

describe("Wallet page — staff views", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockPending.mockReset();
    mockApprove.mockReset();
    mockOfflineCredit.mockReset();
    mockList.mockImplementation((tab: string) =>
      Promise.resolve(
        tab === "recharges"
          ? { items: [PENDING], total: 1, page: 1, size: 100, pages: 1 }
          : { items: [], total: 250, page: 1, size: 100, pages: 3 }
      )
    );
    mockPending.mockResolvedValue([PENDING]);
  });

  it("read-only: tenant ledger with totals, no own-wallet cards, no money actions", async () => {
    state.role = UserRole.READ_ONLY_USER;
    render(<UnifiedWalletPage />);
    expect(await screen.findByText("Spends & Refunds (250)")).toBeInTheDocument();
    expect(screen.getByTestId("wallet.ledger.truncated-note")).toBeInTheDocument();
    expect(screen.queryByText(/Current Wallet Balance/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("wallet.actions.recharge")).not.toBeInTheDocument();
    expect(screen.queryByText(/Approve & Merge/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Settle Cash to Wallet/)).not.toBeInTheDocument();
    expect(mockPending).not.toHaveBeenCalled();
  });

  it("owner: sees the maker-checker queue; Approve asks for confirmation before crediting", async () => {
    state.role = UserRole.OWNER;
    mockApprove.mockResolvedValue({ balance: 433 });
    render(<UnifiedWalletPage />);
    await waitFor(() => expect(mockPending).toHaveBeenCalled());
    expect(await screen.findByText(/Pending UPI Recharges Requiring Admin Approval/)).toBeInTheDocument();
    expect(screen.getByText(/Current Wallet Balance/i)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /Approve & Merge/ })[0]);
    const dialog = await screen.findByTestId("wallet.approve-dialog");
    expect(dialog).toHaveTextContent("customerb2c@logismart.in");
    expect(dialog).toHaveTextContent("640721641527");
    expect(dialog).toHaveTextContent("₹333.00");
    expect(mockApprove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("wallet.approve-dialog.confirm"));
    await waitFor(() => expect(mockApprove).toHaveBeenCalledWith("txn-1", "t"));
  });

  it("operations: own wallet cards but no Recharge button (backend refuses staff recharges)", async () => {
    state.role = UserRole.OPERATIONS_USER;
    render(<UnifiedWalletPage />);
    expect(await screen.findByText(/Current Wallet Balance/i)).toBeInTheDocument();
    expect(screen.queryByTestId("wallet.actions.recharge")).not.toBeInTheDocument();
    expect(screen.queryByText(/Tenant-wide ledger/)).not.toBeInTheDocument();
  });

  it("customer: COD waits for the remittance cycle (no self-settle, #534); owner keeps Settle", async () => {
    state.role = UserRole.CUSTOMER;
    const { unmount } = render(<UnifiedWalletPage />);
    expect(await screen.findByText("Delivered COD awaiting remittance")).toBeInTheDocument();
    expect(screen.getByTestId("wallet.summary.collectible-note")).toBeInTheDocument();
    expect(screen.queryByText(/Settle Cash to Wallet/)).not.toBeInTheDocument();
    expect(screen.getAllByTestId("wallet.actions.recharge").length).toBeGreaterThan(0);
    unmount();

    state.role = UserRole.OWNER;
    render(<UnifiedWalletPage />);
    expect(await screen.findByText(/Settle Cash to Wallet/)).toBeInTheDocument();
  });

  it("owner/admin: can record an offline wallet credit (NEFT/RTGS/Cash) for a customer (#558 3b)", async () => {
    state.role = UserRole.ADMIN;
    mockOfflineCredit.mockResolvedValue({
      balance: 2600,
      transaction: {
        ...PENDING,
        amount: 2500,
        status: WalletTxnStatus.COMPLETED,
        receipt_number: "REC-2627-OFFLINE01",
      },
    });
    render(<UnifiedWalletPage />);
    const openBtn = await screen.findByTestId("wallet.actions.offline-credit");
    fireEvent.click(openBtn);

    expect(await screen.findByTestId("wallet.offline-credit.dialog")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("wallet.offline-credit.user-email"), {
      target: { value: "customerb2c@logismart.in" },
    });
    fireEvent.change(screen.getByTestId("wallet.offline-credit.amount"), {
      target: { value: "2500" },
    });
    fireEvent.change(screen.getByTestId("wallet.offline-credit.utr"), {
      target: { value: "NEFT20261101999" },
    });
    fireEvent.change(screen.getByTestId("wallet.offline-credit.notes"), {
      target: { value: "HDFC bank statement verified" },
    });
    fireEvent.click(screen.getByTestId("wallet.offline-credit.submit"));

    await waitFor(() =>
      expect(mockOfflineCredit).toHaveBeenCalledWith(
        {
          user_email: "customerb2c@logismart.in",
          amount: 2500,
          payment_method: "NEFT",
          utr_number: "NEFT20261101999",
          notes: "HDFC bank statement verified",
        },
        "t"
      )
    );
  });
});
