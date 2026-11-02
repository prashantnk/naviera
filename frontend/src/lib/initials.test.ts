import { describe, expect, it } from "vitest";

import { getInitials } from "./initials";

describe("getInitials", () => {
  it("skips punctuation in tagged display names", () => {
    expect(getInitials("Owner (Test)", "owner@logismart.in")).toBe("OT");
  });

  it("uses the first two words of a full name", () => {
    expect(getInitials("Prashant Kumar Ranjan")).toBe("PK");
  });

  it("uses two letters of a single-word name", () => {
    expect(getInitials("  admin ")).toBe("AD");
  });

  it("falls back to the email local part without separators", () => {
    expect(getInitials("", "o.ps@logismart.in")).toBe("OP");
    expect(getInitials(null, "x@logismart.in")).toBe("X");
  });

  it("returns U when nothing usable is known", () => {
    expect(getInitials(undefined, undefined)).toBe("U");
    expect(getInitials("()", "@")).toBe("U");
  });
});
