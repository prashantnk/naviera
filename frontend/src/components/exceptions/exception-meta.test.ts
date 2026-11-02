import { describe, expect, it } from "vitest";
import { ExceptionCategory, NdrAction, ServiceFlow } from "@/api_client";
import { OPTION_TONE_CLASSES } from "@/lib/form-options";
import {
  B2B_CATEGORY_ORDER,
  B2C_CATEGORY_ORDER,
  BULK_CAPABLE_ACTIONS,
  BULK_ENDPOINT_ACTIONS,
  CATEGORY_ORDER_BY_FLOW,
  EXCEPTION_CATEGORY_META,
  NDR_ACTION_META,
  categoryOptions,
  formatInr,
  visibleExceptionActions,
} from "./exception-meta";

describe("NDR_ACTION_META", () => {
  const actionValues = Object.values(NdrAction);

  it("provides display metadata for every NdrAction member", () => {
    expect(Object.keys(NDR_ACTION_META).sort()).toEqual(actionValues.slice().sort());
    for (const action of actionValues) {
      const meta = NDR_ACTION_META[action];
      expect(meta).toBeDefined();
      expect(meta.label.trim().length).toBeGreaterThan(0);
      expect(meta.description.trim().length).toBeGreaterThan(0);
      expect(meta.icon).toBeTruthy();
      expect(Object.keys(OPTION_TONE_CLASSES)).toContain(meta.tone);
    }
  });

  it("keeps bulk action lists valid NdrAction members", () => {
    for (const action of BULK_CAPABLE_ACTIONS) {
      expect(actionValues).toContain(action);
    }
    for (const action of Array.from(BULK_ENDPOINT_ACTIONS)) {
      expect(actionValues).toContain(action);
    }
  });
});

describe("EXCEPTION_CATEGORY_META and flow category orders", () => {
  const categoryValues = Object.values(ExceptionCategory);

  it("provides label, description, icon, tone and help for every ExceptionCategory", () => {
    expect(Object.keys(EXCEPTION_CATEGORY_META).sort()).toEqual(categoryValues.slice().sort());
    for (const category of categoryValues) {
      const meta = EXCEPTION_CATEGORY_META[category];
      expect(meta).toBeDefined();
      expect(meta.label.trim().length).toBeGreaterThan(0);
      expect(meta.description.trim().length).toBeGreaterThan(0);
      expect(meta.help.trim().length).toBeGreaterThan(0);
      expect(meta.icon).toBeTruthy();
      expect(Object.keys(OPTION_TONE_CLASSES)).toContain(meta.tone);
    }
  });

  it("has 4 B2C categories and 11 B2B categories covering all ExceptionCategory values", () => {
    expect(B2C_CATEGORY_ORDER).toHaveLength(4);
    expect(B2B_CATEGORY_ORDER).toHaveLength(11);
    expect(CATEGORY_ORDER_BY_FLOW[ServiceFlow.B2C]).toBe(B2C_CATEGORY_ORDER);
    expect(CATEGORY_ORDER_BY_FLOW[ServiceFlow.B2B]).toBe(B2B_CATEGORY_ORDER);

    const combined = new Set<ExceptionCategory>(
      B2C_CATEGORY_ORDER.concat(B2B_CATEGORY_ORDER),
    );
    expect(Array.from(combined).sort()).toEqual(categoryValues.slice().sort());
  });

  it("builds SelectOption entries for categoryOptions", () => {
    const options = categoryOptions(B2B_CATEGORY_ORDER);
    expect(options).toHaveLength(11);
    expect(options[0].value).toBe(B2B_CATEGORY_ORDER[0]);
    expect(options[0].label).toBe(EXCEPTION_CATEGORY_META[B2B_CATEGORY_ORDER[0]].label);
  });
});

describe("formatInr", () => {
  it("formats numeric amounts in INR and returns an em dash for missing values", () => {
    expect(formatInr(50)).toContain("50.00");
    expect(formatInr(null)).toBe("—");
    expect(formatInr(undefined)).toBe("—");
    expect(formatInr(Number.NaN)).toBe("—");
  });
});

describe("visibleExceptionActions", () => {
  const actions = [NdrAction.REATTEMPT, NdrAction.RETURN_TO_ORIGIN, NdrAction.ACKNOWLEDGE_CHARGES];

  it("hides every action from the read-only user", () => {
    expect(visibleExceptionActions(actions, { canWrite: false, canAcceptCharges: true })).toEqual([]);
  });

  it("hides wallet-debit actions from operations / support staff", () => {
    expect(visibleExceptionActions(actions, { canWrite: true, canAcceptCharges: false })).toEqual([
      NdrAction.REATTEMPT,
    ]);
  });

  it("keeps every server action for customers and Owner / Admin", () => {
    expect(visibleExceptionActions(actions, { canWrite: true, canAcceptCharges: true })).toEqual(actions);
    expect(visibleExceptionActions(null, { canWrite: true, canAcceptCharges: true })).toEqual([]);
  });
});
