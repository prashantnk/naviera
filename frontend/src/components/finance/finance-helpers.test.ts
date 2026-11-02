// frontend/src/components/finance/finance-helpers.test.ts
import { describe, expect, it } from "vitest";
import {
  documentTypeLabel,
  isWithinDateRange,
  toDateInputValue,
} from "./document-filters";
import {
  CLAIM_STATUS,
  claimBlockReason,
  claimStatusLabel,
  claimStatusOf,
  firstClaimableRow,
  isClaimable,
} from "./weight-claim";
import { readTicketPrefill, ticketNeedsAwb, CLAIMS_FINANCE_CHIP } from "../support/ticket-rules";

describe("GST document filters", () => {
  it("labels note types", () => {
    expect(documentTypeLabel("CREDIT_NOTE")).toBe("Credit note");
    expect(documentTypeLabel("DEBIT_NOTE")).toBe("Debit note");
    expect(documentTypeLabel("INVOICE")).toBe("Invoice");
    expect(documentTypeLabel(undefined)).toBe("Invoice");
  });

  it("formats a date as the date-input value", () => {
    expect(toDateInputValue("2026-10-31")).toMatch(/^2026-10-3[01]$/);
    expect(toDateInputValue("2026-10-31T12:00:00")).toBe("2026-10-31");
    expect(toDateInputValue("not a date")).toBe("");
  });

  it("filters by an inclusive, open-ended date range", () => {
    const day = "2026-10-31T12:00:00";
    expect(isWithinDateRange(day, "", "")).toBe(true);
    expect(isWithinDateRange(day, "2026-10-31", "2026-10-31")).toBe(true);
    expect(isWithinDateRange(day, "2026-11-01", "")).toBe(false);
    expect(isWithinDateRange(day, "", "2026-10-30")).toBe(false);
    expect(isWithinDateRange(day, "2026-10-01", "")).toBe(true);
    expect(isWithinDateRange("garbage", "", "")).toBe(true);
    expect(isWithinDateRange("garbage", "2026-10-01", "")).toBe(false);
  });
});

describe("weight claims", () => {
  const row = (claim_status: string | undefined, cost_diff_inr = 129.8) => ({
    claim_status,
    cost_diff_inr,
  });

  it("normalises the claim status", () => {
    expect(claimStatusOf(row(undefined))).toBe(CLAIM_STATUS.NONE);
    expect(claimStatusOf(row("claim_raised"))).toBe(CLAIM_STATUS.CLAIM_RAISED);
  });

  it("only offers a claim on an unclaimed AWB with an upward charge", () => {
    expect(isClaimable(row("NONE"))).toBe(true);
    expect(isClaimable(row("NONE", 0))).toBe(false);
    expect(isClaimable(row("CLAIM_RAISED"))).toBe(false);
    expect(isClaimable(row("ACCEPTED"))).toBe(false);
  });

  it("uses readable labels and tells staff who acts next", () => {
    expect(claimStatusLabel("CLAIM_RAISED", false)).toBe("Claim under review");
    expect(claimStatusLabel("CLAIM_RAISED", true)).toBe("Awaiting admin review");
    expect(claimStatusLabel("ACCEPTED", false)).toBe("Claim accepted");
    expect(claimStatusLabel("REJECTED", true)).toBe("Claim rejected");
    expect(claimStatusLabel("NONE", false)).toBe("No claim");
  });

  it("pre-fills New Claim with the first claimable row, never a decided one", () => {
    const decided = { ...row("ACCEPTED"), tracking_id: "A" };
    const open = { ...row("CLAIM_RAISED"), tracking_id: "B" };
    const claimable = { ...row("NONE"), tracking_id: "C" };
    expect(firstClaimableRow([decided, open, claimable])?.tracking_id).toBe("C");
    expect(firstClaimableRow([decided, open])).toBeUndefined();
  });

  it("explains why a typed AWB cannot be claimed", () => {
    expect(claimBlockReason(undefined, "X1")).toMatch(/No audited weight discrepancy found for AWB X1/);
    expect(claimBlockReason(row("CLAIM_RAISED"), "X2")).toMatch(/already under review/);
    expect(claimBlockReason(row("REJECTED"), "X3")).toMatch(/already closed \(claim rejected\)/);
    expect(claimBlockReason(row("NONE", 0), "X4")).toMatch(/No extra weight charge/);
    expect(claimBlockReason(row("NONE"), "X5")).toBeNull();
  });
});

describe("support ticket rules", () => {
  it("needs an AWB for shipment issues except Claims / Finance", () => {
    expect(ticketNeedsAwb("SHIPMENT_ISSUE", "Damage / Missing / Mismatch")).toBe(true);
    expect(ticketNeedsAwb("SHIPMENT_ISSUE", CLAIMS_FINANCE_CHIP)).toBe(false);
    expect(ticketNeedsAwb("OTHER_ISSUE", "Account")).toBe(false);
  });

  it("reads the raise-ticket deep link", () => {
    expect(readTicketPrefill("")).toBeNull();
    expect(readTicketPrefill("?tab=RESOLVED")).toBeNull();
    expect(readTicketPrefill("?awb=%20AWB1%20")).toEqual({ awb: "AWB1", category: null });
    expect(
      readTicketPrefill(`?awb=AWB2&category=${encodeURIComponent(CLAIMS_FINANCE_CHIP)}`)
    ).toEqual({ awb: "AWB2", category: CLAIMS_FINANCE_CHIP });
  });
});
