// frontend/src/lib/validations/shipment.test.ts
import { describe, expect, it } from "vitest";
import * as z from "zod";
import { addPackageDimensionIssues, hasMeaningfulReverseDraft } from "./shipment";

/** Runs the shared A-26 rule on a list of boxes and returns the issue paths. */
function issuePaths(packages: Array<{ length: number; breadth: number; height: number }>): string[] {
  const schema = z.array(z.any()).superRefine((value, ctx) => addPackageDimensionIssues(value, ctx));
  const result = schema.safeParse(packages);
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join("."));
}

describe("addPackageDimensionIssues (A-26)", () => {
  it("accepts boxes with real dimensions", () => {
    expect(issuePaths([{ length: 10, breadth: 10, height: 5 }])).toEqual([]);
  });

  it("flags every zero or missing side, per box", () => {
    expect(
      issuePaths([
        { length: 10, breadth: 0, height: 5 },
        { length: 0, breadth: 0, height: Number.NaN },
      ]),
    ).toEqual([
      "packages.0.breadth",
      "packages.1.length",
      "packages.1.breadth",
      "packages.1.height",
    ]);
  });
});

describe("hasMeaningfulReverseDraft (BUG-10 & BUG-06)", () => {
  it("ignores untouched mount defaults on /shipments/new/reverse", () => {
    expect(hasMeaningfulReverseDraft(null)).toBe(false);
    expect(
      hasMeaningfulReverseDraft({
        order_reference_id: "",
        reason_for_return: "",
        qc_required: true,
        qc_notes: "",
        pickup_address_id: "",
        delivery_address_id: "",
        payment_details: {
          freight_payment_mode: "PREPAID" as never,
          is_cod: false,
          cod_amount: 0,
          add_shipping_to_cod: false,
          shipment_value: 0,
          shipment_tax_value: 0,
          shipment_total_value: 0,
          tax_amount: 0,
          base_freight: 0,
          total_logistics_cost: 0,
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
          } as never,
        ],
        documents: [],
      }),
    ).toBe(false);
  });

  it("detects user edits to return fields or box weight/dimensions", () => {
    expect(hasMeaningfulReverseDraft({ reason_for_return: "Wrong size" })).toBe(true);
    expect(
      hasMeaningfulReverseDraft({
        packages: [
          {
            length: 25,
            breadth: 20,
            height: 10,
            weight: 1.5,
            box_count: 1,
            is_fragile: false,
            description: "",
          } as never,
        ],
      }),
    ).toBe(true);
  });
});

