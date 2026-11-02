// frontend/src/components/carrier/delhivery-coordination-playbook.test.tsx
import { ServiceOption, UserRole } from "@/api_client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminCoordinationGuideModal } from "@/components/blocks/admin-coordination-guide-modal";
import { fetchCarrierBilling, type CarrierBillingRead } from "./carrier-api";
import { CarrierBillingPanel } from "./carrier-billing-panel";
import { DelhiveryCoordinationPlaybook } from "./delhivery-coordination-playbook";

const userState = vi.hoisted(() => ({ role: "owner" as string }));

vi.mock("@/components/auth/auth-guard", async () => {
  const caps = await import("@/components/auth/capabilities");
  return {
    useUser: () => ({
      user: { email: "admin@logismart.in", full_name: "Logismart Admin", role: userState.role },
      capabilities: caps.resolveCapabilities(userState.role as UserRole),
      serviceScope: "BOTH",
    }),
  };
});

vi.mock("./carrier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./carrier-api")>();
  return {
    ...actual,
    fetchCarrierBilling: vi.fn(),
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const SHIPMENT_ID = "LOGISMART-2026-0099";

const PENDING_BILLING: CarrierBillingRead = {
  service_option: ServiceOption.DELHIVERY_SURFACE,
  carrier_awb: null,
  charged_weight_kg: null,
  charged_amount: null,
  has_gap: false,
  gap_amount: null,
  gap_message: null,
  seller_billed_amount: 141.6,
};

const SYNCED_BILLING: CarrierBillingRead = {
  service_option: ServiceOption.DELHIVERY_EXPRESS,
  carrier_awb: "1234567890123",
  charged_weight_kg: 1.5,
  charged_amount: 165.0,
  has_gap: false,
  gap_amount: 0,
  gap_message: null,
  seller_billed_amount: 188.8,
};

describe("DelhiveryCoordinationPlaybook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    userState.role = UserRole.OWNER;
  });

  it("renders the 3-column side-by-side playbook expanded by default when AWB is pending for Delhivery options", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(
      <DelhiveryCoordinationPlaybook
        shipmentId={SHIPMENT_ID}
        serviceOption={ServiceOption.DELHIVERY_SURFACE}
        carrierAwb={null}
      />,
    );

    const card = screen.getByTestId("delhivery-coordination-playbook");
    expect(card).toBeInTheDocument();

    // Column 1: Customer Order on Logismart
    expect(screen.getByText(/1\. On Logismart — Customer Order/i)).toBeInTheDocument();
    expect(screen.getByText("Delhivery Surface")).toBeInTheDocument();
    expect(screen.getByText("AWB Pending")).toBeInTheDocument();

    const copyBtn = screen.getByTestId("delhivery-coordination.copy-btn");
    expect(copyBtn).toHaveTextContent(/Copy Details for Delhivery/i);
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining(SHIPMENT_ID));
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining("Delhivery Surface"));
      expect(toast.success).toHaveBeenCalled();
    });

    // Column 2: On one.delhivery.com / Transporter
    expect(screen.getByText(/2\. On one\.delhivery\.com \/ Transporter — Book & Dispatch/i)).toBeInTheDocument();
    expect(screen.getByText(/1\. Open one\.delhivery\.com -> Orders -> Create Order/i)).toBeInTheDocument();
    expect(screen.getByText(/2\. Book shipment & schedule Pickup Request/i)).toBeInTheDocument();
    expect(screen.getByText(/3\. Copy generated Delhivery AWB & billed amount/i)).toBeInTheDocument();

    const externalLink = screen.getByTestId("delhivery-coordination.open-delhivery");
    expect(externalLink).toHaveAttribute("href", "https://one.delhivery.com");
    expect(externalLink).toHaveAttribute("target", "_blank");
    expect(externalLink).toHaveTextContent(/Open one\.delhivery\.com ↗/i);

    // Column 3: Back on Logismart — Sync AWB & Settle Price
    expect(screen.getByText(/3\. Back on Logismart — Sync AWB & Settle Price/i)).toBeInTheDocument();
    expect(screen.getByText(/Enter carrier booking/i)).toBeInTheDocument();
    expect(screen.getByText(/Override \/ Adjust Price/i)).toBeInTheDocument();
  });

  it("renders Prime Transporter steps for PRIME_SURFACE and omits the one.delhivery.com link", () => {
    render(
      <DelhiveryCoordinationPlaybook
        shipmentId={SHIPMENT_ID}
        serviceOption={ServiceOption.PRIME_SURFACE}
        carrierAwb={null}
        transporterName="VRL Logistics"
      />,
    );

    expect(screen.getByText("Logismart Prime")).toBeInTheDocument();
    expect(screen.getByText(/1\. Print 3-Copy LR Docket & 4x6 Box Labels/i)).toBeInTheDocument();
    expect(screen.getByText(/2\. Hand over to assigned Prime Transporter \(VRL Logistics\)/i)).toBeInTheDocument();
    expect(screen.getByText(/3\. Collect Transporter LR\/GR number & actual weight/i)).toBeInTheDocument();
    expect(screen.queryByTestId("delhivery-coordination.open-delhivery")).not.toBeInTheDocument();
  });

  it("uses Partner fallback when PRIME_SURFACE has no transporterName and supports collapsing once AWB is saved", () => {
    render(
      <DelhiveryCoordinationPlaybook
        shipmentId={SHIPMENT_ID}
        serviceOption={ServiceOption.PRIME_SURFACE}
        carrierAwb="LR-998877"
        transporterName={null}
      />,
    );

    expect(screen.getByText("Synced: LR-998877")).toBeInTheDocument();
    expect(screen.getByText(/2\. Hand over to assigned Prime Transporter \(Partner\)/i)).toBeInTheDocument();

    const toggleBtn = screen.getByTestId("delhivery-coordination.toggle");
    fireEvent.click(toggleBtn);
    expect(screen.queryByText(/3\. Collect Transporter LR\/GR number & actual weight/i)).not.toBeInTheDocument();

    fireEvent.click(toggleBtn);
    expect(screen.getByText(/3\. Collect Transporter LR\/GR number & actual weight/i)).toBeInTheDocument();
  });

  it("integrates into CarrierBillingPanel for staff who canOperate and hides for read-only staff", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(PENDING_BILLING);
    const { unmount } = render(
      <CarrierBillingPanel
        shipmentId={SHIPMENT_ID}
        tenantSlug="logismart-test"
        serviceOption={ServiceOption.DELHIVERY_SURFACE}
      />,
    );

    expect(await screen.findByTestId("delhivery-coordination-playbook")).toBeInTheDocument();
    unmount();

    userState.role = UserRole.READ_ONLY_USER;
    vi.mocked(fetchCarrierBilling).mockResolvedValue(SYNCED_BILLING);
    render(
      <CarrierBillingPanel
        shipmentId={SHIPMENT_ID}
        tenantSlug="logismart-test"
        serviceOption={ServiceOption.DELHIVERY_EXPRESS}
      />,
    );

    expect(await screen.findByTestId("carrier-billing.awb")).toHaveTextContent("1234567890123");
    expect(screen.queryByTestId("delhivery-coordination-playbook")).not.toBeInTheDocument();
  });
});

describe("AdminCoordinationGuideModal", () => {
  it("renders the 3-column comparison table across all 6 operational workflows", () => {
    render(<AdminCoordinationGuideModal open={true} onOpenChange={vi.fn()} />);

    const modal = screen.getByTestId("admin-coordination-guide-modal");
    expect(modal).toBeInTheDocument();

    expect(screen.getByText("What Customer Does on Logismart")).toBeInTheDocument();
    expect(screen.getByText("What Admin Does on one.delhivery.com / Hub")).toBeInTheDocument();
    expect(screen.getByText("What Admin Does on Logismart")).toBeInTheDocument();

    expect(screen.getByText(/B2C Parcel Booking & AWB Sync/i)).toBeInTheDocument();
    expect(
      screen.getByText(/B2B Cargo: Logismart Prime vs\. Delhivery B2B & Door vs\. Godown/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Pickup Requests & Hub Dimension\/Weight Audit/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Overpriced \/ Underpriced Admin Price Override \(Wallet Refund \/ Debit \+ GST Notes\)/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Delivery Exceptions \(NDR\) & Return to Origin \(RTO\)/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Wallet Recharges \(Maker-Checker UPI & Offline NEFT\/Cash Credit\)/i),
    ).toBeInTheDocument();
  });
});
