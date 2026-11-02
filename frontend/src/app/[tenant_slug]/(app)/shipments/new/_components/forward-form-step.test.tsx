// frontend/src/app/[tenant_slug]/(app)/shipments/new/_components/forward-form-step.test.tsx
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FormProvider, useForm } from "react-hook-form";

import { FreightPaymentMode, ServiceType, ShipmentType } from "@/api_client";
import { Form } from "@/components/ui/form";
import type { ForwardShipmentFormValues } from "@/lib/validations/shipment";

import { ForwardFormStep } from "./forward-form-step";

vi.mock("@/components/auth/auth-guard", () => ({
  useUser: () => ({
    isAdmin: false,
    capabilities: { isStaff: false },
  }),
}));

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({
    tenant: { name: "Logismart", slug: "logismart-test" },
    tenantSlug: "logismart-test",
    routeTo: (p: string) => `/logismart-test${p}`,
  }),
}));

vi.mock("@/components/booking/use-shipment-valuation", () => ({
  useShipmentValuation: () => ({ valuation: null, isLoading: false }),
}));

function TestHarness({
  ewayBillRequired = false,
  hsnCode = "",
}: {
  ewayBillRequired?: boolean;
  hsnCode?: string;
}) {
  const form = useForm<ForwardShipmentFormValues>({
    defaultValues: {
      order_reference_id: "",
      service_type: ServiceType.SURFACE_ROAD,
      shipment_type: ShipmentType.FORWARD,
      product_category: undefined,
      other_category_description: "",
      payment_details: {
        freight_payment_mode: FreightPaymentMode.PREPAID,
        is_cod: false,
        cod_amount: 0,
        add_shipping_to_cod: false,
        shipment_value: ewayBillRequired ? 60000 : 500,
        shipment_tax_value: 0,
        shipment_total_value: ewayBillRequired ? 60000 : 500,
        tax_amount: 0,
        base_freight: 0,
        total_logistics_cost: 0,
        hsn_code: hsnCode,
        invoice_number: "",
        invoice_date: "",
        eway_bill_number: "",
        eway_bill_required: ewayBillRequired,
      },
      packages: [
        {
          length: 10,
          breadth: 10,
          height: 10,
          weight: 0.5,
          box_count: 1,
          is_fragile: false,
          description: "",
        },
      ],
      documents: [],
      pickup_address_id: "",
      delivery_address_id: "",
    },
  });

  return (
    <FormProvider {...form}>
      <Form {...form}>
        <ForwardFormStep
          control={form.control}
          savedAddresses={[]}
          addShippingToCod={false}
          setAddShippingToCod={() => {}}
          docFields={[]}
          removeDoc={() => {}}
          isUploading={false}
          handleFileUpload={async () => {}}
        />
      </Form>
    </FormProvider>
  );
}

describe("ForwardFormStep — progressive disclosure for B2C booking", () => {
  afterEach(() => {
    cleanup();
  });

  it("collapses optional tax & compliance fields by default when shipment <= ₹50,000 while keeping primary fields visible", () => {
    render(<TestHarness ewayBillRequired={false} />);

    // Primary booking inputs remain visible upfront
    expect(screen.getByTestId("booking.shipment.category")).toBeTruthy();
    expect(screen.getByTestId("booking.payment.goods-value")).toBeTruthy();
    expect(screen.getByTestId("booking.payment.goods-total")).toBeTruthy();
    expect(screen.getByTestId("booking.payment.mode")).toBeTruthy();
    expect(screen.getByTestId("booking.payment.cod-toggle")).toBeTruthy();

    // Optional compliance section is collapsed with clear badge
    expect(screen.getByTestId("booking.compliance.badge").textContent).toContain(
      "Optional (Required only above ₹50,000)"
    );
    expect(screen.queryByTestId("booking.compliance.content")).toBeNull();
    expect(screen.queryByPlaceholderText("e.g. 8517")).toBeNull();
  });

  it("expands and collapses optional compliance details when user clicks the toggle", () => {
    render(<TestHarness ewayBillRequired={false} />);

    const toggle = screen.getByTestId("booking.compliance.toggle");
    fireEvent.click(toggle);

    expect(screen.getByTestId("booking.compliance.content")).toBeTruthy();
    expect(screen.getByPlaceholderText("e.g. 8517")).toBeTruthy();
    expect(screen.getByPlaceholderText("e.g. INV-992")).toBeTruthy();

    fireEvent.click(toggle);
    expect(screen.queryByTestId("booking.compliance.content")).toBeNull();
  });

  it("auto-expands compliance section and shows E-Way Bill input when eway_bill_required is true (> ₹50,000)", () => {
    render(<TestHarness ewayBillRequired={true} />);

    expect(screen.getByTestId("booking.compliance.badge").textContent).toContain(
      "Required above ₹50,000"
    );
    expect(screen.getByTestId("booking.compliance.content")).toBeTruthy();
    expect(screen.getByTestId("booking.payment.eway-bill")).toBeTruthy();
  });

  it("ensures Invoice Date DatePicker, FormItems, and file upload row use w-full min-w-0 and never overflow with w-[280px]", () => {
    render(<TestHarness ewayBillRequired={false} />);

    fireEvent.click(screen.getByTestId("booking.compliance.toggle"));

    const datePickerButton = screen.getByRole("button", { name: /pick a date/i });
    expect(datePickerButton.className).toContain("w-full");
    expect(datePickerButton.className).toContain("min-w-0");
    expect(datePickerButton.className).not.toContain("w-[280px]");

    const formItem = datePickerButton.closest('[data-slot="form-item"]');
    expect(formItem?.className).toContain("min-w-0");

    const fileInput = document.getElementById("sandbox-file-upload");
    expect(fileInput).toBeTruthy();
    expect(fileInput?.className).toContain("w-full");
    expect(fileInput?.className).toContain("min-w-0");
    expect(fileInput?.parentElement?.className).toContain("min-w-0");
  });
});
