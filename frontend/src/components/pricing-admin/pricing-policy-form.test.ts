// frontend/src/components/pricing-admin/pricing-policy-form.test.ts
import { describe, expect, it } from "vitest";

import { MarkupMode, ServiceOption, type PricingPolicy } from "./pricing-admin-api";
import {
  describeMarkup,
  describePolicyChanges,
  formValuesToPolicy,
  hasCompleteCodFee,
  LANE_MARKUP,
  NOT_SET_TEXT,
  policyToFormValues,
  pricingPolicySchema,
  supportsLaneMarkup,
  toEditablePolicy,
  type PricingPolicyFormValues,
} from "./pricing-policy-form";

const SAVED: PricingPolicy = {
  delhivery_markup_percent: 0,
  prime_default_markup_percent: 20,
  cod_fee_percent: null,
  cod_fee_min: null,
  enabled_options: [ServiceOption.PRIME_SURFACE, ServiceOption.DELHIVERY_SURFACE],
  option_markups: {},
};

function values(overrides: Partial<PricingPolicyFormValues> = {}): PricingPolicyFormValues {
  return Object.assign(policyToFormValues(SAVED), overrides);
}

/** Form values with one markup row replaced. */
function withMarkup(option: ServiceOption, mode: string, value: string): PricingPolicyFormValues {
  const base = values();
  return Object.assign({}, base, {
    markups: Object.assign({}, base.markups, { [option]: { mode, value } }),
  });
}

describe("policyToFormValues", () => {
  it("shows the backend defaults when no per-option markup is stored", () => {
    const form = policyToFormValues(SAVED);
    expect(form.markups[ServiceOption.DELHIVERY_SURFACE]).toEqual({ mode: MarkupMode.PERCENT, value: "0" });
    expect(form.markups[ServiceOption.DELHIVERY_B2B_SURFACE]).toEqual({ mode: MarkupMode.PERCENT, value: "0" });
    expect(form.markups[ServiceOption.PRIME_SURFACE]).toEqual({ mode: LANE_MARKUP, value: "" });
    expect(form.cod_fee_min).toBe("");
    expect(form.enabled_options).toEqual([ServiceOption.DELHIVERY_SURFACE, ServiceOption.PRIME_SURFACE]);
  });

  it("shows stored per-option rules (percent or flat ₹)", () => {
    const form = policyToFormValues(
      Object.assign({}, SAVED, {
        option_markups: {
          [ServiceOption.DELHIVERY_EXPRESS]: { mode: MarkupMode.FLAT, value: 25 },
          [ServiceOption.PRIME_SURFACE]: { mode: MarkupMode.PERCENT, value: 15 },
        },
      }),
    );
    expect(form.markups[ServiceOption.DELHIVERY_EXPRESS]).toEqual({ mode: MarkupMode.FLAT, value: "25" });
    expect(form.markups[ServiceOption.PRIME_SURFACE]).toEqual({ mode: MarkupMode.PERCENT, value: "15" });
  });
});

describe("formValuesToPolicy", () => {
  it("sends no markup entries when nothing was changed, and empty COD boxes as null", () => {
    expect(formValuesToPolicy(values({ cod_fee_min: "  " }), SAVED)).toEqual({
      delhivery_markup_percent: 0,
      prime_default_markup_percent: 20,
      cod_fee_min: null,
      cod_fee_percent: null,
      enabled_options: [ServiceOption.DELHIVERY_SURFACE, ServiceOption.PRIME_SURFACE],
      option_markups: {},
    });
  });

  it("stores a flat ₹ markup for one option only", () => {
    const policy = formValuesToPolicy(withMarkup(ServiceOption.DELHIVERY_B2B_SURFACE, MarkupMode.FLAT, " 150 "), SAVED);
    expect(policy.option_markups).toEqual({
      [ServiceOption.DELHIVERY_B2B_SURFACE]: { mode: MarkupMode.FLAT, value: 150 },
    });
  });

  it("stores a Prime override and drops it again when switched back to lane markups", () => {
    const override = formValuesToPolicy(withMarkup(ServiceOption.PRIME_SURFACE, MarkupMode.PERCENT, "12.5"), SAVED);
    expect(override.option_markups).toEqual({
      [ServiceOption.PRIME_SURFACE]: { mode: MarkupMode.PERCENT, value: 12.5 },
    });
    const back = formValuesToPolicy(policyToFormValues(SAVED), override);
    expect(back.option_markups).toEqual({});
  });

  it("keeps an existing entry even when it equals the default", () => {
    const stored = Object.assign({}, SAVED, {
      option_markups: { [ServiceOption.DELHIVERY_SURFACE]: { mode: MarkupMode.PERCENT, value: 0 } },
    });
    expect(formValuesToPolicy(policyToFormValues(stored), stored).option_markups).toEqual({
      [ServiceOption.DELHIVERY_SURFACE]: { mode: MarkupMode.PERCENT, value: 0 },
    });
  });

  it("round-trips a fully set policy", () => {
    const full: PricingPolicy = Object.assign({}, SAVED, {
      cod_fee_min: 30,
      cod_fee_percent: 1.5,
      enabled_options: [ServiceOption.DELHIVERY_SURFACE, ServiceOption.DELHIVERY_EXPRESS, ServiceOption.PRIME_SURFACE],
      option_markups: { [ServiceOption.DELHIVERY_EXPRESS]: { mode: MarkupMode.FLAT, value: 20 } },
    });
    expect(formValuesToPolicy(policyToFormValues(full), full)).toEqual(full);
  });
});

describe("pricingPolicySchema", () => {
  it("accepts zero markups, lane markups and empty COD values", () => {
    expect(pricingPolicySchema.safeParse(values()).success).toBe(true);
  });

  it.each([
    [MarkupMode.PERCENT, ""],
    [MarkupMode.PERCENT, "-1"],
    [MarkupMode.PERCENT, "abc"],
    [MarkupMode.PERCENT, "101"],
    [MarkupMode.FLAT, "100001"],
  ])("rejects a %s markup of %j", (mode, raw) => {
    const result = pricingPolicySchema.safeParse(withMarkup(ServiceOption.DELHIVERY_SURFACE, mode, raw));
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toEqual(["markups", ServiceOption.DELHIVERY_SURFACE, "value"]);
    }
  });

  it("accepts a flat markup above 100 rupees", () => {
    expect(pricingPolicySchema.safeParse(withMarkup(ServiceOption.DELHIVERY_SURFACE, MarkupMode.FLAT, "250")).success).toBe(true);
  });

  it("tells the admin to use 0 when a markup is blank", () => {
    const result = pricingPolicySchema.safeParse(withMarkup(ServiceOption.DELHIVERY_EXPRESS, MarkupMode.FLAT, " "));
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.issues[0].message).toContain("use 0 for none");
  });

  it.each([
    ["cod_fee_min", "-5"],
    ["cod_fee_min", "10001"],
    ["cod_fee_percent", "1e9"],
    ["cod_fee_percent", "x"],
  ])("rejects %s = %j", (field, raw) => {
    const result = pricingPolicySchema.safeParse(values({ [field]: raw } as Partial<PricingPolicyFormValues>));
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.issues[0].path).toEqual([field]);
  });
});

describe("hasCompleteCodFee", () => {
  it.each([
    ["", "", false],
    ["30", "", false],
    ["", "1.5", false],
    [" ", "1.5", false],
    ["30", "1.5", true],
    ["0", "0", true],
  ])("min=%j pct=%j -> %s", (min, pct, expected) => {
    expect(hasCompleteCodFee({ cod_fee_min: min, cod_fee_percent: pct })).toBe(expected);
  });
});

describe("describeMarkup / supportsLaneMarkup", () => {
  it("words each rule plainly", () => {
    expect(describeMarkup({ mode: MarkupMode.PERCENT, value: "10" })).toBe("10%");
    expect(describeMarkup({ mode: MarkupMode.FLAT, value: "25" })).toBe("₹25 per shipment");
    expect(describeMarkup({ mode: LANE_MARKUP, value: "" })).toBe("Each lane's own markup");
  });

  it("offers lane markups for Prime only", () => {
    expect(supportsLaneMarkup(ServiceOption.PRIME_SURFACE)).toBe(true);
    expect(supportsLaneMarkup(ServiceOption.DELHIVERY_B2B_SURFACE)).toBe(false);
  });
});

describe("describePolicyChanges", () => {
  it("returns nothing when the policy is unchanged (option order ignored)", () => {
    const reordered = Object.assign({}, SAVED, {
      enabled_options: [ServiceOption.DELHIVERY_SURFACE, ServiceOption.PRIME_SURFACE],
    });
    expect(describePolicyChanges(SAVED, reordered)).toEqual([]);
  });

  it("treats an explicit entry equal to the default as no change", () => {
    const explicit = Object.assign({}, SAVED, {
      option_markups: { [ServiceOption.DELHIVERY_SURFACE]: { mode: MarkupMode.PERCENT, value: 0 } },
    });
    expect(describePolicyChanges(SAVED, explicit)).toEqual([]);
  });

  it("lists each changed setting in plain English", () => {
    const next: PricingPolicy = {
      delhivery_markup_percent: 0,
      prime_default_markup_percent: 20,
      cod_fee_min: 30,
      cod_fee_percent: 1.5,
      enabled_options: [],
      option_markups: {
        [ServiceOption.DELHIVERY_EXPRESS]: { mode: MarkupMode.FLAT, value: 25 },
        [ServiceOption.PRIME_SURFACE]: { mode: MarkupMode.PERCENT, value: 10 },
      },
    };
    expect(describePolicyChanges(SAVED, next)).toEqual([
      { label: "Delhivery Express markup", before: "0%", after: "₹25 per shipment" },
      { label: "Logismart Prime markup", before: "Each lane's own markup", after: "10%" },
      { label: "COD fee minimum", before: NOT_SET_TEXT, after: "₹30" },
      { label: "COD fee percentage", before: NOT_SET_TEXT, after: "1.5%" },
      {
        label: "Services customers can book",
        before: "Delhivery Surface, Logismart Prime",
        after: "None",
      },
    ]);
  });
});

describe("toEditablePolicy", () => {
  it("drops the computed flags", () => {
    expect(
      toEditablePolicy(
        Object.assign({ cod_enabled: false, delhivery_configured: true, delhivery_b2b_configured: false }, SAVED),
      ),
    ).toEqual(SAVED);
  });
});
