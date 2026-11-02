import { describe, expect, it } from "vitest";

import {
  companyPatchFromValues,
  companyValuesFromSettings,
  storedInvoicePrefix,
} from "./company-profile";
import { sectionLabel } from "./settings-history-drawer";
import { sectionForErrors } from "./settings-sections";

describe("sectionForErrors", () => {
  it("opens the section holding the first invalid field", () => {
    expect(sectionForErrors(["escalation_matrix"])).toBe("support");
    expect(sectionForErrors(["company", "brand"])).toBe("company");
    expect(sectionForErrors(["wallet_config"])).toBe("wallet");
    expect(sectionForErrors(["hero_block"])).toBe("website");
  });

  it("returns null when no key maps to a section", () => {
    expect(sectionForErrors([])).toBeNull();
    expect(sectionForErrors(["root"])).toBeNull();
  });
});

const FIXTURE = {
  gstin: "06AAECL2138H1ZQ",
  company: {
    pan: "AAECL2138H",
    gstin: "06AAECL2138H1ZQ",
    legal_name: "LOGISMART PRIVATE LIMITED",
    contact_email: "logismartprivatelimited@gmail.com",
    contact_phone: "9821008627",
    registered_address: "H. NO-632/5, GALI NO-3, PATEL NAGAR, Gurgaon, Haryana, 122001",
    invoice_prefix: "LTST",
  },
  contact: { gstin: "06AAECL2138H1ZQ", address: "632/5, Patel Nagar\nGurgaon" },
  wallet_config: { gstin: "06AAECL2138H1ZQ", merchant_name: "LOGISMART PVT" },
};

describe("companyValuesFromSettings", () => {
  it("reads the supplier identity from settings.company (what GST documents print)", () => {
    const values = companyValuesFromSettings(FIXTURE);
    expect(values.legal_name).toBe("LOGISMART PRIVATE LIMITED");
    expect(values.registered_address).toContain("H. NO-632/5");
    expect(values.pan).toBe("AAECL2138H");
    expect(values.contact_phone).toBe("9821008627");
  });

  it("falls back to the legacy keys the backend also falls back to", () => {
    const values = companyValuesFromSettings({
      gstin: "27AAACL9999A1Z2",
      contact: { address: "Old contact address" },
      wallet_config: { merchant_name: "Acme Logistics" },
    });
    expect(values.gstin).toBe("27AAACL9999A1Z2");
    expect(values.registered_address).toBe("Old contact address");
    expect(values.legal_name).toBe("Acme Logistics");
    expect(values.pan).toBe("");
  });

  it("returns blank values for missing or malformed settings", () => {
    expect(companyValuesFromSettings(undefined).gstin).toBe("");
    expect(companyValuesFromSettings({ company: "oops" }).legal_name).toBe("");
  });
});

describe("companyPatchFromValues", () => {
  it("trims, upper-cases GSTIN/PAN and turns blanks into null", () => {
    const patch = companyPatchFromValues({
      legal_name: "  Logismart Pvt Ltd ",
      gstin: "06aaecl2138h1zq",
      pan: " aaecl2138h",
      registered_address: "",
      contact_email: "  ",
      contact_phone: "9821008627",
    });
    expect(patch).toEqual({
      legal_name: "Logismart Pvt Ltd",
      gstin: "06AAECL2138H1ZQ",
      pan: "AAECL2138H",
      registered_address: null,
      contact_email: null,
      contact_phone: "9821008627",
    });
  });

  it("never sends the locked invoice prefix", () => {
    const patch = companyPatchFromValues(companyValuesFromSettings(FIXTURE));
    expect(Object.keys(patch)).not.toContain("invoice_prefix");
  });
});

describe("storedInvoicePrefix", () => {
  it("returns the configured prefix or null", () => {
    expect(storedInvoicePrefix(FIXTURE)).toBe("LTST");
    expect(storedInvoicePrefix({ company: { invoice_prefix: "  " } })).toBeNull();
    expect(storedInvoicePrefix(null)).toBeNull();
  });
});

describe("settings history section labels", () => {
  it("names every section the backend records, including pricing and role changes", () => {
    expect(sectionLabel("company")).toBe("Company Profile");
    expect(sectionLabel("pricing_policy")).toBe("Pricing");
    expect(sectionLabel("user_roles")).toBe("User role change");
    expect(sectionLabel("something_new")).toBe("something_new");
  });
});
