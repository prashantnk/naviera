// frontend/src/lib/validations/b2b-forward-booking.test.ts
import {
  FreightPaymentMode,
  PickupStrategy,
  ProductCategory,
  ServiceType,
  ShipmentType,
} from "@/api_client";
import { describe, expect, it } from "vitest";

import {
  b2bForwardBookingSchema,
  b2bForwardShipmentSchema,
  hasBookingFormShape,
  MAX_PO_NUMBERS,
  splitPoNumbers,
} from "./shipment";

/** The B2B wizard's default values: what "Compare B2B Rates" validates on an untouched form. */
function emptyForm(): Record<string, unknown> {
  return {
    order_reference_id: "",
    service_type: ServiceType.SURFACE_ROAD,
    shipment_type: ShipmentType.FORWARD,
    product_category: undefined,
    po_number: "",
    pickup_strategy: PickupStrategy.DEFAULT,
    is_blind_pickup: false,
    estimated_box_count: null,
    is_carriers_risk: false,
    door_delivery: false,
    payment_details: {
      freight_payment_mode: FreightPaymentMode.PREPAID,
      is_cod: false,
      cod_amount: 0,
      add_shipping_to_cod: false,
      shipment_value: 0,
      shipment_tax_value: 0,
      shipment_total_value: 0,
      invoice_numbers: [],
      eway_bill_numbers: [],
      eway_bill_required: false,
    },
    packages: [{ length: 0, breadth: 0, height: 0, weight: 10, box_count: 1 }],
    documents: [],
  };
}

/** A complete, bookable LR (saved addresses, one box, one invoice). */
function validForm(): Record<string, unknown> {
  const form = emptyForm();
  return {
    ...form,
    product_category: ProductCategory.COMMERCIAL,
    pickup_address_id: "pickup-1",
    delivery_address_id: "delivery-1",
    packages: [{ length: 60, breadth: 40, height: 40, weight: 18, box_count: 3 }],
    payment_details: {
      ...(form.payment_details as Record<string, unknown>),
      shipment_value: 60000,
      invoice_numbers: ["INV-1"],
    },
  };
}

/** Issue paths (dot-joined) of a failed parse. */
function issuePaths(result: { success: boolean; error?: { issues: { path: PropertyKey[] }[] } }): string[] {
  return result.success ? [] : (result.error?.issues ?? []).map((issue) => issue.path.join("."));
}

describe("B2B forward LR booking validation", () => {
  it("reports every missing field on the first Compare, not just the category", () => {
    const paths = issuePaths(b2bForwardBookingSchema.safeParse(emptyForm()));
    expect(paths).toEqual(
      expect.arrayContaining([
        "product_category",
        "pickup_address_id",
        "delivery_address_id",
        "packages.0.length",
        "payment_details.shipment_value",
        "payment_details.invoice_numbers",
      ]),
    );
  });

  it("accepts a complete LR", () => {
    expect(issuePaths(b2bForwardBookingSchema.safeParse(validForm()))).toEqual([]);
  });

  it("requires a GST invoice number (blank rows do not count)", () => {
    const form = validForm();
    (form.payment_details as Record<string, unknown>).invoice_numbers = ["  "];
    expect(issuePaths(b2bForwardBookingSchema.safeParse(form))).toEqual([
      "payment_details.invoice_numbers",
    ]);
  });

  it("requires the e-way bill when the backend valuation says so", () => {
    const form = validForm();
    (form.payment_details as Record<string, unknown>).eway_bill_required = true;
    expect(issuePaths(b2bForwardBookingSchema.safeParse(form))).toEqual([
      "payment_details.eway_bill_numbers",
    ]);
  });

  it("allows up to 5 comma-separated PO numbers and rejects a 6th", () => {
    const ok = { ...validForm(), po_number: "PO-1, PO-2,PO-3 , PO-4, PO-5" };
    expect(issuePaths(b2bForwardBookingSchema.safeParse(ok))).toEqual([]);
    const tooMany = { ...validForm(), po_number: "1,2,3,4,5,6" };
    expect(issuePaths(b2bForwardBookingSchema.safeParse(tooMany))).toEqual(["po_number"]);
  });

  it("keeps the edit schema free of the create-only invoice/value rules", () => {
    const legacy = validForm();
    (legacy.payment_details as Record<string, unknown>).invoice_numbers = [];
    (legacy.payment_details as Record<string, unknown>).shipment_value = 0;
    expect(issuePaths(b2bForwardShipmentSchema.safeParse(legacy))).toEqual([]);
  });
});

describe("splitPoNumbers / hasBookingFormShape", () => {
  it("splits, trims and drops empty PO entries", () => {
    expect(splitPoNumbers(" PO-1 ,, PO-2 ,")).toEqual(["PO-1", "PO-2"]);
    expect(splitPoNumbers(undefined)).toEqual([]);
    expect(MAX_PO_NUMBERS).toBe(5);
  });

  it("only runs cross-field rules on form-shaped values", () => {
    expect(hasBookingFormShape({ value: { payment_details: {}, packages: [] } })).toBe(true);
    expect(hasBookingFormShape({ value: { payment_details: null, packages: [] } })).toBe(false);
    expect(hasBookingFormShape({ value: { payment_details: {} } })).toBe(false);
    expect(hasBookingFormShape({ value: null })).toBe(false);
  });
});
