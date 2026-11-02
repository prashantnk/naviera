// frontend/src/components/carrier/carrier-billing-panel.test.tsx
import { ServiceOption, UserRole } from "@/api_client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyAdminShipmentCharge,
  fetchCarrierBilling,
  saveCarrierBilling,
  type CarrierBillingRead,
} from "./carrier-api";
import { CarrierBillingPanel } from "./carrier-billing-panel";
import { AWB_NOT_ASSIGNED_TEXT } from "./carrier-info";

const userState = vi.hoisted(() => ({ role: "owner" as string }));

vi.mock("@/components/auth/auth-guard", async () => {
  const caps = await import("@/components/auth/capabilities");
  return {
    useUser: () => ({ capabilities: caps.resolveCapabilities(userState.role as UserRole) }),
  };
});

vi.mock("./carrier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./carrier-api")>();
  return {
    ...actual,
    fetchCarrierBilling: vi.fn(),
    saveCarrierBilling: vi.fn(),
    applyAdminShipmentCharge: vi.fn(),
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SHIPMENT_ID = "11111111-1111-1111-1111-111111111111";

const EMPTY_BILLING: CarrierBillingRead = {
  service_option: ServiceOption.DELHIVERY_SURFACE,
  carrier_awb: null,
  charged_weight_kg: null,
  charged_amount: null,
  has_gap: false,
  gap_amount: null,
  gap_message: null,
};

const GAP_BILLING: CarrierBillingRead = {
  service_option: ServiceOption.DELHIVERY_EXPRESS,
  carrier_awb: "1234567890123",
  charged_weight_kg: 2.5,
  charged_amount: 310.5,
  has_gap: true,
  gap_amount: 38.35,
  gap_message: "Carrier charged ₹263.14 + GST vs ₹224.79 + GST billed to the seller: ₹38.35 not recovered.",
  seller_billed_amount: 265.25,
  seller_billed_taxable: 224.79,
  carrier_charged_taxable: 263.14,
  margin_amount: -38.35,
  gap_gross_amount: 45.25,
};

describe("CarrierBillingPanel with DelhiveryCoordinationPlaybook", () => {
  beforeEach(() => {
    vi.mocked(fetchCarrierBilling).mockReset();
    vi.mocked(saveCarrierBilling).mockReset();
    vi.mocked(applyAdminShipmentCharge).mockReset();
    userState.role = UserRole.OWNER;
  });

  it("renders the 3-column Delhivery coordination playbook and empty carrier booking for ops staff", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(EMPTY_BILLING);
    render(
      <CarrierBillingPanel
        shipmentId={SHIPMENT_ID}
        tenantSlug="logismart-test"
        serviceOption={ServiceOption.DELHIVERY_SURFACE}
      />,
    );

    expect(await screen.findByTestId("delhivery-coordination-playbook")).toBeInTheDocument();
    expect(screen.getByTestId("carrier-billing.awb")).toHaveTextContent(AWB_NOT_ASSIGNED_TEXT);
    expect(screen.getByTestId("carrier-billing.edit")).toHaveTextContent("Enter carrier booking");
  });

  it("supports bidirectional price override and 1-click gap recovery", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(GAP_BILLING);
    vi.mocked(applyAdminShipmentCharge).mockResolvedValue({
      ...GAP_BILLING,
      has_gap: false,
      gap_amount: 0,
      seller_billed_amount: 199.0,
    });

    render(
      <CarrierBillingPanel
        shipmentId={SHIPMENT_ID}
        tenantSlug="logismart-test"
        serviceOption={ServiceOption.DELHIVERY_EXPRESS}
      />,
    );

    const openBtn = await screen.findByTestId("carrier-billing.add-charge.open");
    fireEvent.click(openBtn);
    fireEvent.change(screen.getByTestId("carrier-billing.add-charge.amount"), {
      target: { value: "199.00" },
    });
    fireEvent.change(screen.getByTestId("carrier-billing.add-charge.label"), {
      target: { value: "Overpriced lane refund" },
    });
    fireEvent.click(screen.getByTestId("carrier-billing.add-charge.submit"));

    await waitFor(() =>
      expect(applyAdminShipmentCharge).toHaveBeenCalledWith(
        SHIPMENT_ID,
        { override_total_price: 199, label: "Overpriced lane refund" },
        "logismart-test",
      ),
    );
  });
});
