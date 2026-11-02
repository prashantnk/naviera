// frontend/src/components/carrier/carrier-components.test.tsx
import { ApiError, ServiceOption, UserRole } from "@/api_client";
import { resolveCapabilities } from "@/components/auth/capabilities";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyAdminShipmentCharge,
  fetchCarrierBilling,
  saveCarrierBilling,
  awbFieldCopy,
  serviceOptionLabel,
  type CarrierBillingRead,
} from "./carrier-api";
import { CarrierBillingPanel } from "./carrier-billing-panel";
import { CarrierBookingDialog } from "./carrier-booking-dialog";
import { AWB_NOT_ASSIGNED_TEXT, CarrierInfo } from "./carrier-info";

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
const DUPLICATE_MESSAGE = "AWB 1234567890123 is already used by shipment LS-0001.";

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
};

/** Builds the ApiError the generated client throws for an HTTP error. */
function apiError(status: number, detail: string): ApiError {
  return new ApiError(
    { method: "PUT", url: "/api/v1/shipments/{shipment_id}/carrier-billing" },
    { url: "", ok: false, status, statusText: "", body: { detail } },
    "error",
  );
}

function renderPanel() {
  return render(
    <CarrierBillingPanel
      shipmentId={SHIPMENT_ID}
      tenantSlug="logismart-test"
      carrierName="Delhivery"
      carrierAwb="9999"
      serviceOption={ServiceOption.DELHIVERY_SURFACE}
    />,
  );
}

beforeEach(() => {
  vi.mocked(fetchCarrierBilling).mockReset();
  vi.mocked(saveCarrierBilling).mockReset();
  vi.mocked(applyAdminShipmentCharge).mockReset();
  userState.role = UserRole.OWNER;
});

describe("serviceOptionLabel", () => {
  it("maps every option and passes unknown or empty values through", () => {
    expect(serviceOptionLabel(ServiceOption.DELHIVERY_SURFACE)).toBe("Delhivery Surface");
    expect(serviceOptionLabel(ServiceOption.DELHIVERY_EXPRESS)).toBe("Delhivery Express");
    expect(serviceOptionLabel(ServiceOption.PRIME_SURFACE)).toBe("Logismart Prime");
    expect(serviceOptionLabel("NEW_OPTION")).toBe("NEW_OPTION");
    expect(serviceOptionLabel(null)).toBeNull();
  });
});


describe("awbFieldCopy", () => {
  it("names the AWB field after who carries the parcel", () => {
    expect(awbFieldCopy(ServiceOption.DELHIVERY_SURFACE).label).toBe("Delhivery AWB");
    expect(awbFieldCopy(ServiceOption.PRIME_SURFACE).label).toBe("Transporter AWB / LR number");
    expect(awbFieldCopy(ServiceOption.DELHIVERY_B2B_SURFACE).label).toBe("Delhivery LRN");
    expect(awbFieldCopy(undefined).description).toContain("one.delhivery.com");
  });
});
describe("CarrierInfo", () => {
  it("shows the empty state when no AWB is assigned", () => {
    render(<CarrierInfo carrierName="Delhivery" carrierAwb={null} />);
    expect(screen.getByTestId("carrier-info.empty")).toHaveTextContent(AWB_NOT_ASSIGNED_TEXT);
    expect(screen.queryByTestId("carrier-info.copy")).not.toBeInTheDocument();
  });

  it("shows carrier, service label and AWB, and copies the AWB", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <CarrierInfo carrierName="Delhivery" carrierAwb="1234567890123" serviceOption={ServiceOption.DELHIVERY_EXPRESS} />,
    );
    expect(screen.getByTestId("carrier-info.name")).toHaveTextContent("Delhivery");
    expect(screen.getByTestId("carrier-info.service")).toHaveTextContent("Delhivery Express");
    expect(screen.getByTestId("carrier-info.awb")).toHaveTextContent("1234567890123");
    fireEvent.click(screen.getByTestId("carrier-info.copy"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("1234567890123"));
  });
});

describe("CarrierBillingPanel", () => {
  it("customers see the read-only carrier line and never call the staff endpoint", () => {
    userState.role = UserRole.CUSTOMER;
    renderPanel();
    expect(screen.getByTestId("carrier-info.awb")).toHaveTextContent("9999");
    expect(screen.queryByTestId("carrier-billing.edit")).not.toBeInTheDocument();
    expect(fetchCarrierBilling).not.toHaveBeenCalled();
  });

  it("ops staff see the empty state and the 'Enter carrier booking' button", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(EMPTY_BILLING);
    renderPanel();
    expect(await screen.findByTestId("carrier-billing.awb")).toHaveTextContent(AWB_NOT_ASSIGNED_TEXT);
    expect(screen.getByTestId("carrier-billing.service-option")).toHaveTextContent("Delhivery Surface");
    expect(screen.getByTestId("carrier-billing.edit")).toHaveTextContent("Enter carrier booking");
    expect(screen.queryByTestId("carrier-billing.no-gap-badge")).not.toBeInTheDocument();
    expect(fetchCarrierBilling).toHaveBeenCalledWith(SHIPMENT_ID, "logismart-test");
  });

  it("read-only staff see the values and the gap, but no form", async () => {
    userState.role = UserRole.READ_ONLY_USER;
    vi.mocked(fetchCarrierBilling).mockResolvedValue(GAP_BILLING);
    renderPanel();
    expect(await screen.findByTestId("carrier-billing.awb")).toHaveTextContent("1234567890123");
    expect(screen.getByTestId("carrier-billing.gap-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("carrier-billing.edit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("carrier-billing.form")).not.toBeInTheDocument();
  });


  it("shows seller price, carrier charge and the backend margin without an alert for a positive margin", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue({
      service_option: ServiceOption.PRIME_SURFACE,
      carrier_awb: "LRN-77",
      charged_weight_kg: 12,
      charged_amount: 118,
      has_gap: false,
      gap_amount: 0,
      gap_message: null,
      seller_billed_amount: 141.6,
      seller_billed_taxable: 120,
      carrier_charged_taxable: 100,
      margin_amount: 20,
    });
    renderPanel();
    expect(await screen.findByTestId("carrier-billing.margin")).toHaveTextContent("₹20.00 (₹120.00 − ₹100.00)");
    expect(screen.getByTestId("carrier-billing.seller-billed")).toHaveTextContent("₹141.60");
    expect(screen.getByText("Carrier charged amount (incl. GST)")).toBeInTheDocument();
    expect(screen.getByTestId("carrier-billing.no-gap-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("carrier-billing.gap-alert")).not.toBeInTheDocument();
  });

  it("labels an under-recovery as a negative margin", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(GAP_BILLING);
    renderPanel();
    expect(await screen.findByTestId("carrier-billing.gap-badge")).toHaveTextContent("Negative margin ₹38.35");
    expect(screen.getByTestId("carrier-billing.margin")).toHaveTextContent("-₹38.35");
    expect(screen.getByText("Delhivery charged amount (incl. GST)")).toBeInTheDocument();
  });
  it.each([403, 404])("falls back to the read-only line when the API answers %i", async (status) => {
    userState.role = UserRole.SUPPORT_USER;
    vi.mocked(fetchCarrierBilling).mockRejectedValue(apiError(status, "Nope"));
    renderPanel();
    expect(await screen.findByTestId("carrier-info.awb")).toHaveTextContent("9999");
  });

  it("shows the load error with a retry", async () => {
    vi.mocked(fetchCarrierBilling)
      .mockRejectedValueOnce(apiError(500, "Server exploded"))
      .mockResolvedValueOnce(EMPTY_BILLING);
    renderPanel();
    expect(await screen.findByTestId("carrier-billing.error")).toHaveTextContent("Server exploded");
    fireEvent.click(screen.getByTestId("carrier-billing.retry"));
    expect(await screen.findByTestId("carrier-billing.edit")).toBeInTheDocument();
  });

  it("saves the booking and shows the backend's gap verdict", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(EMPTY_BILLING);
    vi.mocked(saveCarrierBilling).mockResolvedValue(GAP_BILLING);
    renderPanel();
    fireEvent.click(await screen.findByTestId("carrier-billing.edit"));
    fireEvent.change(screen.getByTestId("carrier-billing.form.awb"), { target: { value: " 1234567890123 " } });
    fireEvent.change(screen.getByTestId("carrier-billing.form.charged-weight"), { target: { value: "2.5" } });
    fireEvent.change(screen.getByTestId("carrier-billing.form.charged-amount"), { target: { value: "310.5" } });
    fireEvent.click(screen.getByTestId("carrier-billing.form.submit"));

    expect(await screen.findByTestId("carrier-billing.gap-alert")).toBeInTheDocument();
    expect(saveCarrierBilling).toHaveBeenCalledWith(
      SHIPMENT_ID,
      { carrier_awb: "1234567890123", charged_weight_kg: 2.5, charged_amount: 310.5 },
      "logismart-test",
    );
    expect(screen.getByTestId("carrier-billing.gap-amount")).toHaveTextContent("₹38.35");
    expect(screen.getByTestId("carrier-billing.gap-message")).toHaveTextContent(GAP_BILLING.gap_message!);
    expect(screen.queryByTestId("carrier-billing.form")).not.toBeInTheDocument();
    expect(screen.getByTestId("carrier-billing.edit")).toHaveTextContent("Edit carrier booking");
  });

  it("sends null for blank optional fields and shows the no-gap badge", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(EMPTY_BILLING);
    vi.mocked(saveCarrierBilling).mockResolvedValue({ ...EMPTY_BILLING, carrier_awb: "555" });
    renderPanel();
    fireEvent.click(await screen.findByTestId("carrier-billing.edit"));
    fireEvent.change(screen.getByTestId("carrier-billing.form.awb"), { target: { value: "555" } });
    fireEvent.click(screen.getByTestId("carrier-billing.form.submit"));

    expect(await screen.findByTestId("carrier-billing.no-gap-badge")).toBeInTheDocument();
    expect(saveCarrierBilling).toHaveBeenCalledWith(
      SHIPMENT_ID,
      { carrier_awb: "555", charged_weight_kg: null, charged_amount: null },
      "logismart-test",
    );
  });

  it("blocks submit without an AWB or with an invalid weight", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(EMPTY_BILLING);
    renderPanel();
    fireEvent.click(await screen.findByTestId("carrier-billing.edit"));
    fireEvent.change(screen.getByTestId("carrier-billing.form.charged-weight"), { target: { value: "0" } });
    fireEvent.click(screen.getByTestId("carrier-billing.form.submit"));

    expect(await screen.findByText("Enter the AWB from one.delhivery.com.")).toBeInTheDocument();
    expect(screen.getByText("Enter a weight above 0 kg, or leave it blank.")).toBeInTheDocument();
    expect(saveCarrierBilling).not.toHaveBeenCalled();
  });

  it("shows the backend's duplicate-AWB (409) message under the AWB field", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(EMPTY_BILLING);
    vi.mocked(saveCarrierBilling).mockRejectedValue(apiError(409, DUPLICATE_MESSAGE));
    renderPanel();
    fireEvent.click(await screen.findByTestId("carrier-billing.edit"));
    fireEvent.change(screen.getByTestId("carrier-billing.form.awb"), { target: { value: "1234567890123" } });
    fireEvent.click(screen.getByTestId("carrier-billing.form.submit"));

    expect(await screen.findByTestId("carrier-billing.form.awb-error")).toHaveTextContent(DUPLICATE_MESSAGE);
    expect(screen.getByTestId("carrier-billing.form")).toBeInTheDocument();
  });

  it("cancel closes the form without saving", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(GAP_BILLING);
    renderPanel();
    fireEvent.click(await screen.findByTestId("carrier-billing.edit"));
    expect(screen.getByTestId("carrier-billing.form.awb")).toHaveValue("1234567890123");
    fireEvent.click(screen.getByTestId("carrier-billing.form.cancel"));
    expect(screen.queryByTestId("carrier-billing.form")).not.toBeInTheDocument();
    expect(saveCarrierBilling).not.toHaveBeenCalled();
  });

  it("allows Owner/Admin to override final price (overpriced refund or underpriced debit) and hides it from ops", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue({
      ...GAP_BILLING,
      gap_gross_amount: 45.25,
    });
    vi.mocked(applyAdminShipmentCharge).mockResolvedValue({
      ...GAP_BILLING,
      has_gap: false,
      gap_amount: 0,
      seller_billed_amount: 199.0,
    });
    renderPanel();

    const openBtn = await screen.findByTestId("carrier-billing.add-charge.open");
    expect(openBtn).toHaveTextContent("Override / Adjust Price");
    expect(screen.getByTestId("carrier-billing.recover-gap")).toHaveTextContent(
      "Recover Difference from Customer (₹45.25 incl. GST)"
    );

    fireEvent.click(openBtn);
    expect(screen.getByTestId("carrier-billing.add-charge.current-price")).toHaveTextContent("₹265.25");
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
        "logismart-test"
      )
    );
  });
});

describe("CarrierBookingDialog", () => {
  it("loads carrier billing only after the ops button is clicked", async () => {
    vi.mocked(fetchCarrierBilling).mockResolvedValue(EMPTY_BILLING);
    render(<CarrierBookingDialog shipmentId={SHIPMENT_ID} tenantSlug="logismart-test" trackingId="LS-0001" />);
    expect(fetchCarrierBilling).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("carrier-booking-dialog.LS-0001.open"));
    expect(await screen.findByTestId("carrier-billing.edit")).toHaveTextContent("Enter carrier booking");
    expect(fetchCarrierBilling).toHaveBeenCalledTimes(1);
  });
});

describe("capability mapping used by the panel", () => {
  it("only owner / admin / operations get the form", () => {
    expect(resolveCapabilities(UserRole.OPERATIONS_USER).canOperate).toBe(true);
    expect(resolveCapabilities(UserRole.SUPPORT_USER).canOperate).toBe(false);
    expect(resolveCapabilities(UserRole.READ_ONLY_USER).canOperate).toBe(false);
  });
});
