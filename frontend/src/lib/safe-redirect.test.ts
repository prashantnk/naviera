import { describe, expect, it } from "vitest";

import { DEFAULT_POST_LOGIN_PATH, sanitizeNextPath } from "./safe-redirect";

describe("sanitizeNextPath", () => {
  it("keeps normal in-app paths", () => {
    expect(sanitizeNextPath("/shipments/abc")).toBe("/shipments/abc");
    expect(sanitizeNextPath("/b2b/shipments?page=2")).toBe("/b2b/shipments?page=2");
  });

  it("falls back when missing", () => {
    expect(sanitizeNextPath(null)).toBe(DEFAULT_POST_LOGIN_PATH);
    expect(sanitizeNextPath(undefined)).toBe(DEFAULT_POST_LOGIN_PATH);
    expect(sanitizeNextPath("")).toBe(DEFAULT_POST_LOGIN_PATH);
  });

  it.each([
    "//evil.com",
    "/\\evil.com",
    "https://evil.com",
    "javascript:alert(1)",
    "evil.com/dashboard",
    "/redirect?to=https://evil.com",
    "/\tevil",
  ])("rejects unsafe value %s", (value) => {
    expect(sanitizeNextPath(value)).toBe(DEFAULT_POST_LOGIN_PATH);
  });

  it("honours a custom fallback", () => {
    expect(sanitizeNextPath("//x", "/b2b/dashboard")).toBe("/b2b/dashboard");
  });
});
