// frontend/src/app/[tenant_slug]/(app)/disputes/weight-mismatch/weight-mismatch-page.test.tsx
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WeightMismatchDisputesPage from "./page";

const mockList = vi.fn();
const mockRaise = vi.fn();
const mockUseUser = vi.fn();

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    DisputesService: {
      listWeightMismatchDisputes: (...a: unknown[]) => mockList(...a),
      raiseWeightMismatchClaims: (...a: unknown[]) => mockRaise(...a),
      resolveWeightMismatchDispute: vi.fn(),
    },
  };
});
vi.mock("@/components/auth/auth-guard", () => ({ useUser: () => mockUseUser() }));
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ tenant: null, tenantSlug: "logismart-test", routeTo: (p: string) => `/t${p}` }),
}));

const customer = {
  capabilities: { isStaff: false, canWrite: true, canManageFinance: false },
};

function dispute(tracking_id: string, claim_status: string, extra: Record<string, unknown> = {}) {
  return {
    id: `id-${tracking_id}`,
    tenant_id: "t",
    merchant_user_id: "m",
    tracking_id,
    shipment_id: `s-${tracking_id}`,
    shipment_status: "Delivered",
    manifested_weight_g: 1000,
    charged_weight_g: 3000,
    cost_diff_inr: 129.8,
    claim_status,
    raised_at: "2026-10-31T03:41:00",
    updated_at: "2026-10-31T03:41:00",
    merchant_email: "seller@example.com",
    ...extra,
  };
}

describe("Weight mismatch page", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockRaise.mockReset();
    mockUseUser.mockReturnValue(customer);
  });

  it("shows readable claim states, closed remarks and Need help? on a rejected claim", async () => {
    mockList.mockResolvedValue([
      dispute("AWB-REJ", "REJECTED", { claim_remarks: "Scan confirmed 3 kg" }),
      dispute("AWB-ACC", "ACCEPTED"),
      dispute("AWB-OPEN", "CLAIM_RAISED"),
      dispute("AWB-NEW", "NONE"),
    ]);
    render(<WeightMismatchDisputesPage />);

    expect((await screen.findAllByTestId("weight-mismatch.row.AWB-REJ.claim-status"))[0]).toHaveTextContent(
      "Claim rejected"
    );
    expect(screen.getAllByTestId("weight-mismatch.row.AWB-ACC.claim-status")[0]).toHaveTextContent("Claim accepted");
    expect(screen.getAllByTestId("weight-mismatch.row.AWB-OPEN.claim-status")[0]).toHaveTextContent(
      "Claim under review"
    );
    expect(screen.getAllByText("Scan confirmed 3 kg").length).toBeGreaterThan(0);
    const needHelp = screen.getAllByTestId("weight-mismatch.row.AWB-REJ.need-help")[0];
    expect(needHelp.getAttribute("href")).toContain("/t/support?awb=AWB-REJ&category=");
    expect(screen.queryByText(/CLAIM_RAISED/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Updated On/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Zone Mismatch/)).not.toBeInTheDocument();
    expect(screen.queryByText("seller@example.com")).not.toBeInTheDocument();
  });

  it("pre-fills New Claim with the first claimable AWB, not a decided one", async () => {
    mockList.mockResolvedValue([dispute("AWB-ACC", "ACCEPTED"), dispute("AWB-NEW", "NONE")]);
    render(<WeightMismatchDisputesPage />);
    fireEvent.click(await screen.findByTestId("weight-mismatch.actions.new-claim"));

    expect(await screen.findByText("Create New Claim")).toBeInTheDocument();
    expect(screen.getByText("AWB# AWB-NEW")).toBeInTheDocument();
    expect(screen.getByText(/Weight audited on/)).toBeInTheDocument();
    expect(screen.queryByText(/Delivered on/)).not.toBeInTheDocument();
  });

  it("submits a claim for the selected AWB", async () => {
    mockList.mockResolvedValue([dispute("AWB-NEW", "NONE")]);
    mockRaise.mockResolvedValue([]);
    render(<WeightMismatchDisputesPage />);
    const [raise] = await screen.findAllByTestId("weight-mismatch.row.AWB-NEW.raise-claim");
    fireEvent.click(raise);
    fireEvent.change(await screen.findByTestId("weight-mismatch.claim.weight"), {
      target: { value: "1200" },
    });
    fireEvent.click(screen.getByTestId("weight-mismatch.claim.submit"));
    await waitFor(() => expect(mockRaise).toHaveBeenCalledTimes(1));
    expect(mockRaise.mock.calls[0][0]).toMatchObject({
      tracking_ids: ["AWB-NEW"],
      claimed_weight_g: 1200,
    });
  });

  it("hides claim actions from read-only staff and labels open claims for staff", async () => {
    mockUseUser.mockReturnValue({
      capabilities: { isStaff: true, canWrite: false, canManageFinance: false },
    });
    mockList.mockResolvedValue([dispute("AWB-NEW", "NONE"), dispute("AWB-OPEN", "CLAIM_RAISED")]);
    render(<WeightMismatchDisputesPage />);

    expect((await screen.findAllByTestId("weight-mismatch.row.AWB-OPEN.claim-status"))[0]).toHaveTextContent(
      "Awaiting admin review"
    );
    expect(screen.queryByTestId("weight-mismatch.actions.new-claim")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weight-mismatch.row.AWB-NEW.raise-claim")).not.toBeInTheDocument();
    expect(screen.getByTestId("weight-mismatch.row.AWB-NEW.merchant")).toHaveTextContent("seller@example.com");
    const row = screen.getByTestId("weight-mismatch.row.AWB-OPEN");
    expect(within(row).queryByRole("button", { name: /Accept/ })).not.toBeInTheDocument();
  });

  it("lets a finance admin accept or reject an open claim", async () => {
    mockUseUser.mockReturnValue({
      capabilities: { isStaff: true, canWrite: true, canManageFinance: true },
    });
    mockList.mockResolvedValue([dispute("AWB-OPEN", "CLAIM_RAISED")]);
    render(<WeightMismatchDisputesPage />);
    const row = await screen.findByTestId("weight-mismatch.row.AWB-OPEN");
    expect(within(row).getByRole("button", { name: /Accept/ })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Reject/ })).toBeInTheDocument();
  });
});
