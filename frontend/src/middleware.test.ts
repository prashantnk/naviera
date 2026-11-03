import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";
import middleware, {
  normalizeHostname,
  parseCustomDomainTenants,
} from "./middleware";

const ORIGINAL_CUSTOM_DOMAINS = process.env.CUSTOM_DOMAIN_TENANTS;

afterEach(() => {
  if (ORIGINAL_CUSTOM_DOMAINS === undefined) {
    delete process.env.CUSTOM_DOMAIN_TENANTS;
  } else {
    process.env.CUSTOM_DOMAIN_TENANTS = ORIGINAL_CUSTOM_DOMAINS;
  }
});

function makeRequest(url: string, hostHeader?: string): NextRequest {
  const parsed = new URL(url);
  const headers = new Headers();
  headers.set("host", hostHeader ?? parsed.host);
  return new NextRequest(parsed, { headers });
}

describe("middleware custom-domain parsing & routing", () => {
  it("parses CUSTOM_DOMAIN_TENANTS entries and ignores malformed tokens", () => {
    const map = parseCustomDomainTenants(
      " logismart.in:logismart , WWW.LOGISMART.IN : logismart , invalid-entry, :missinghost, hostonly:, a:b:c ",
    );
    expect(Array.from(map.entries())).toEqual([
      ["logismart.in", "logismart"],
      ["www.logismart.in", "logismart"],
    ]);
    expect(parseCustomDomainTenants(undefined).size).toBe(0);
    expect(parseCustomDomainTenants("").size).toBe(0);
  });

  it("normalizes Host headers with optional ports and casing", () => {
    expect(normalizeHostname("LogiSmart.IN:3000")).toBe("logismart.in");
    expect(normalizeHostname("www.logismart.in")).toBe("www.logismart.in");
    expect(normalizeHostname(null)).toBe("");
  });

  it("rewrites mapped custom domains (including www) to /<slug>/... in subdomain mode", () => {
    process.env.CUSTOM_DOMAIN_TENANTS =
      "logismart.in:logismart,www.logismart.in:logismart";

    const rootRes = middleware(makeRequest("https://logismart.in/"));
    expect(rootRes.headers.get("x-middleware-rewrite")).toBe(
      "https://logismart.in/logismart",
    );
    expect(rootRes.headers.get("x-middleware-override-headers")).toContain(
      "x-routing-mode",
    );
    expect(rootRes.headers.get("x-middleware-request-x-routing-mode")).toBe(
      "subdomain",
    );

    const wwwLoginRes = middleware(
      makeRequest("https://www.logismart.in/login?next=%2Fdashboard"),
    );
    expect(wwwLoginRes.headers.get("x-middleware-rewrite")).toBe(
      "https://www.logismart.in/logismart/login?next=%2Fdashboard",
    );
    expect(wwwLoginRes.headers.get("x-middleware-request-x-routing-mode")).toBe(
      "subdomain",
    );

    const alreadyPrefixedRes = middleware(
      makeRequest("https://logismart.in/logismart/shipments"),
    );
    expect(alreadyPrefixedRes.headers.get("x-middleware-rewrite")).toBe(
      "https://logismart.in/logismart/shipments",
    );
  });

  it("preserves existing subdomain and path routing for unmapped hosts", () => {
    process.env.CUSTOM_DOMAIN_TENANTS =
      "logismart.in:logismart,www.logismart.in:logismart";

    // Subdomain on naviera.com rewrites to /<slug>/...
    const subRes = middleware(
      makeRequest("https://logismart.naviera.com/dashboard"),
    );
    expect(subRes.headers.get("x-middleware-rewrite")).toBe(
      "https://logismart.naviera.com/logismart/dashboard",
    );
    expect(subRes.headers.get("x-middleware-request-x-routing-mode")).toBe(
      "subdomain",
    );

    // Unknown host on root rewrites to /naviera in path mode
    const unknownRootRes = middleware(
      makeRequest("https://naviera.vercel.app/"),
    );
    expect(unknownRootRes.headers.get("x-middleware-rewrite")).toBe(
      "https://naviera.vercel.app/naviera",
    );
    expect(
      unknownRootRes.headers.get("x-middleware-request-x-routing-mode"),
    ).toBe("path");

    // Unknown host with explicit /<slug>/... passes through in path mode
    const pathSlugRes = middleware(
      makeRequest("https://naviera.vercel.app/logismart/login"),
    );
    expect(pathSlugRes.headers.get("x-middleware-rewrite")).toBeNull();
    expect(pathSlugRes.headers.get("x-middleware-next")).toBe("1");
    expect(pathSlugRes.headers.get("x-middleware-request-x-routing-mode")).toBe(
      "path",
    );
  });
});
