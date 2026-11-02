// frontend/src/components/pricing-admin/prime-lanes-logic.test.ts
import { describe, expect, it } from "vitest";

import type { PrimeImportReport, PrimeLaneRead } from "./pricing-admin-api";
import {
  buildLanePatch,
  filterLanes,
  formatImportIssue,
  laneToDraft,
  MAX_CSV_BYTES,
  summarizeImportReport,
  validateCsvFile,
} from "./prime-lanes-logic";

function lane(overrides: Partial<PrimeLaneRead> = {}): PrimeLaneRead {
  return Object.assign(
    {
      id: "lane-1",
      origin_zone: "Delhi NCR",
      dest_zone: "Mumbai",
      mode: "SURFACE",
      transporter_name: "Vision Express",
      tat_hours: 72,
      rate_per_kg: 8,
      min_lr_charge: 500,
      docket_charge: 100,
      min_chargeable_kg: 50,
      volumetric_divisor: 4500,
      max_dimension_cm: 240,
      delivery_type: "GODOWN",
      oda_per_kg: 2,
      oda_min: 800,
      odd_weight_per_kg: 2,
      odd_weight_min: 800,
      pickup_per_kg: 1,
      pickup_min: 600,
      door_delivery_per_kg: 1,
      door_delivery_min: 600,
      markup_percent: 20,
      is_active: true,
      updated_at: "2026-10-30T12:00:00",
    },
    overrides,
  );
}

function report(overrides: Partial<PrimeImportReport> = {}): PrimeImportReport {
  return Object.assign({ created: 0, updated: 0, deactivated: 0, errors: [], warnings: [] }, overrides);
}

describe("buildLanePatch", () => {
  it("sends only the fields that changed", () => {
    const draft = Object.assign(laneToDraft(lane()), { rate_per_kg: " 9.5 ", markup_percent: "20" });
    expect(buildLanePatch(lane(), draft)).toEqual({ patch: { rate_per_kg: 9.5 }, errors: {} });
  });

  it("returns an empty patch when nothing changed", () => {
    expect(buildLanePatch(lane(), laneToDraft(lane()))).toEqual({ patch: {}, errors: {} });
  });

  it("allows 0 for charges and markup but not for rate or TAT", () => {
    const draft = Object.assign(laneToDraft(lane()), {
      docket_charge: "0",
      markup_percent: "0",
      rate_per_kg: "0",
      tat_hours: "0",
    });
    const result = buildLanePatch(lane(), draft);
    expect(result.patch).toEqual({});
    expect(result.errors).toEqual({
      rate_per_kg: "Rate / kg must be more than 0",
      tat_hours: "TAT must be more than 0",
    });
  });

  it.each([
    ["tat_hours", "", "TAT is required"],
    ["tat_hours", "36.5", "TAT must be a whole number"],
    ["tat_hours", "721", "TAT cannot be more than 720"],
    ["min_lr_charge", "-1", "Min LR cannot be negative"],
    ["docket_charge", "abc", "Docket must be a number"],
    ["markup_percent", "150", "Markup cannot be more than 100"],
  ])("rejects %s = %j", (field, raw, message) => {
    const draft = Object.assign(laneToDraft(lane()), { [field]: raw });
    const result = buildLanePatch(lane(), draft);
    expect(result.errors).toEqual({ [field]: message });
    expect(result.patch).toEqual({});
  });
});

describe("filterLanes", () => {
  const lanes = [
    lane({ id: "a", dest_zone: "Mumbai", transporter_name: "Vision Express" }),
    lane({ id: "b", dest_zone: "Ahmedabad", transporter_name: "Gati" }),
  ];

  it("returns every lane for a blank search", () => {
    expect(filterLanes(lanes, "  ").map((l) => l.id)).toEqual(["a", "b"]);
  });

  it("matches zones and transporter case-insensitively", () => {
    expect(filterLanes(lanes, "ahmed").map((l) => l.id)).toEqual(["b"]);
    expect(filterLanes(lanes, "VISION").map((l) => l.id)).toEqual(["a"]);
    expect(filterLanes(lanes, "delhi").map((l) => l.id)).toEqual(["a", "b"]);
    expect(filterLanes(lanes, "pune")).toEqual([]);
  });
});

describe("validateCsvFile", () => {
  it("accepts a normal .csv file", () => {
    expect(validateCsvFile({ name: "Lanes.CSV", size: 2048 })).toBeNull();
  });

  it.each([
    [{ name: "lanes.xlsx", size: 10 }, "Choose a .csv file"],
    [{ name: "lanes.csv", size: 0 }, "This file is empty."],
    [{ name: "lanes.csv", size: MAX_CSV_BYTES + 1 }, "larger than 1 MB"],
  ])("rejects %j", (file, message) => {
    expect(validateCsvFile(file)).toContain(message);
  });
});

describe("formatImportIssue", () => {
  it("prefixes the CSV row when known", () => {
    expect(formatImportIssue({ row: 12, message: "rate_per_kg is NA" })).toBe("Row 12: rate_per_kg is NA");
    expect(formatImportIssue({ row: null, message: "Missing column TAT" })).toBe("Missing column TAT");
  });
});

describe("summarizeImportReport", () => {
  it("previews the change counts with correct plurals", () => {
    expect(summarizeImportReport(report({ created: 1, updated: 3, deactivated: 0 }), true)).toEqual({
      headline: "1 lane will be added, 3 lanes will be updated and 0 lanes will be switched off.",
      blocked: false,
      noChanges: false,
    });
  });

  it("uses the past tense after a real import", () => {
    expect(summarizeImportReport(report({ deactivated: 2 }), false).headline).toBe(
      "0 lanes were added, 0 lanes were updated and 2 lanes were switched off.",
    );
  });

  it("blocks the import when any row has an error (server is all-or-nothing)", () => {
    const result = summarizeImportReport(
      report({ created: 5, errors: [{ row: 3, message: "bad" }, { row: 4, message: "bad" }] }),
      true,
    );
    expect(result.blocked).toBe(true);
    expect(result.headline).toBe("2 rows have problems. Nothing will be imported until the file is fixed.");
    expect(summarizeImportReport(report({ errors: [{ row: 3, message: "bad" }] }), true).headline).toMatch(
      /^1 row has a problem\./,
    );
  });

  it("says when the file changes nothing (warnings alone do not block)", () => {
    const result = summarizeImportReport(report({ warnings: [{ row: 2, message: "state looks wrong" }] }), true);
    expect(result).toEqual({
      headline: "This file matches your current lanes. Nothing would change.",
      blocked: false,
      noChanges: true,
    });
  });
});
