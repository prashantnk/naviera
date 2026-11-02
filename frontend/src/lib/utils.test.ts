// frontend/src/lib/utils.test.ts
import { ApiError } from "@/api_client";
import { describe, expect, it } from "vitest";
import {
  extractApiErrorMessage,
  formatIstDate,
  formatIstDateTime,
  formatValidationLocation,
  parseUtcDate,
  safeFormatDate,
} from "./utils";

function apiError(status: number, body: unknown): ApiError {
  return new ApiError(
    { method: "POST", url: "/api/v1/x" },
    { url: "/api/v1/x", ok: false, status, statusText: "", body },
    "Unprocessable Entity",
  );
}

describe("formatValidationLocation", () => {
  it("drops the request root and humanises field names", () => {
    expect(formatValidationLocation(["body", "delivery_address", "pincode"])).toBe(
      "Delivery address › Pincode",
    );
  });

  it("turns list indexes into 1-based item numbers", () => {
    expect(formatValidationLocation(["body", "packages", 0, "weight"])).toBe("Packages #1 › Weight");
  });

  it("returns empty text for missing or non-field locations", () => {
    expect(formatValidationLocation(undefined)).toBe("");
    expect(formatValidationLocation(["body"])).toBe("");
  });
});

describe("extractApiErrorMessage (F-08)", () => {
  it("returns a string detail unchanged", () => {
    expect(extractApiErrorMessage(apiError(400, { detail: "Wallet balance is low." }))).toBe(
      "Wallet balance is low.",
    );
  });

  it("names the field in a 422 and strips Pydantic's 'Value error,' prefix", () => {
    const err = apiError(422, {
      detail: [{ loc: ["body", "phone"], msg: "Value error, Enter a 10-digit mobile number", type: "value_error" }],
    });
    expect(extractApiErrorMessage(err)).toBe("Phone: Enter a 10-digit mobile number");
  });

  it("summarises several 422 errors and always returns a string", () => {
    const err = apiError(422, {
      detail: [
        { loc: ["body", "packages", 1, "length"], msg: "Input should be greater than 0" },
        { loc: ["body", "email"], msg: "Field required" },
      ],
    });
    const message = extractApiErrorMessage(err);
    expect(typeof message).toBe("string");
    expect(message).toBe("Packages #2 › Length: Input should be greater than 0 (+1 more)");
  });

  it("reads object details and raw axios errors", () => {
    expect(extractApiErrorMessage(apiError(409, { detail: { message: "Duplicate AWB" } }))).toBe(
      "Duplicate AWB",
    );
    expect(extractApiErrorMessage({ response: { data: { detail: "Slot full" } } })).toBe("Slot full");
  });

  it("falls back for unreadable errors", () => {
    expect(extractApiErrorMessage(null, "Could not save")).toBe("Could not save");
    expect(extractApiErrorMessage(apiError(422, { detail: [{ loc: ["body"] }] }), "Bad input")).toBe(
      "Unprocessable Entity",
    );
  });
});

describe("IST date/time helpers (F-02)", () => {
  it("treats naive ISO datetime strings from FastAPI as UTC", () => {
    // 2026-10-29T20:00:00 UTC is 2026-10-30 01:30:00 IST (+05:30).
    const parsed = parseUtcDate("2026-10-29T20:00:00");
    expect(parsed?.toISOString()).toBe("2026-10-29T20:00:00.000Z");
    expect(safeFormatDate("2026-10-29T20:00:00", "dd MMM yyyy, hh:mm a")).toBe(
      "30 Oct 2026, 01:30 AM",
    );
    expect(formatIstDate("2026-10-29T20:00:00")).toContain("30");
    expect(formatIstDateTime("2026-10-29T20:00:00")).toMatch(/30.*0?1:30/i);
  });

  it("preserves calendar-date-only strings without shifting to the previous day", () => {
    expect(safeFormatDate("2026-10-30", "dd MMM yyyy")).toBe("30 Oct 2026");
  });

  it("returns fallback for empty or invalid dates", () => {
    expect(safeFormatDate(null)).toBe("-");
    expect(safeFormatDate("not-a-date")).toBe("-");
    expect(formatIstDate(undefined)).toBe("—");
    expect(formatIstDateTime("")).toBe("—");
  });
});
