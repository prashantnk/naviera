// src/middleware.ts
import { APP_CONFIG } from "@/lib/config";
import { NextRequest, NextResponse } from "next/server";

export const config = {
  matcher: [
    // Added a regex group at the end to ignore all common image files and proxies
    "/((?!api|supabase-proxy|_next/static|_next/image|favicon.ico|health|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};

/**
 * Parses `CUSTOM_DOMAIN_TENANTS` (e.g. `"logismart.in:logismart,www.logismart.in:logismart"`)
 * into a lowercase `host -> tenant_slug` lookup map.
 */
export function parseCustomDomainTenants(
  raw: string | undefined = process.env.CUSTOM_DOMAIN_TENANTS,
): Map<string, string> {
  const map = new Map<string, string>();
  if (!raw) return map;

  for (const entry of raw.split(",")) {
    const trimmed = entry.trim();
    if (!trimmed) continue;
    const colonIndex = trimmed.indexOf(":");
    if (colonIndex <= 0) continue;
    const host = trimmed.slice(0, colonIndex).trim().toLowerCase();
    const slug = trimmed.slice(colonIndex + 1).trim().toLowerCase();
    if (host && slug && !slug.includes(":")) {
      map.set(host, slug);
    }
  }
  return map;
}

/**
 * Normalizes a `Host` header value by stripping any `:port` suffix and lowercasing.
 */
export function normalizeHostname(hostHeader: string | null | undefined): string {
  return (hostHeader || "").trim().toLowerCase().replace(/:\d+$/, "");
}

export default function middleware(req: NextRequest) {
  const url = req.nextUrl;
  const hostname = normalizeHostname(req.headers.get("host"));

  const isLocal = hostname.includes(APP_CONFIG.DOMAINS.LOCALHOST);
  const isCodespace = hostname.includes(APP_CONFIG.DOMAINS.CODESPACE_SUFFIX);
  const isProduction = hostname.includes(APP_CONFIG.DOMAINS.PRODUCTION);

  const customDomainTenants = parseCustomDomainTenants(
    process.env.CUSTOM_DOMAIN_TENANTS,
  );
  const customTenantSlug = customDomainTenants.get(hostname);

  let subdomain = "";
  const parts = hostname.split(".");

  if (customTenantSlug) {
    subdomain = customTenantSlug;
  } else if (isLocal && parts.length > 1) {
    subdomain = parts[0];
  } else if (isProduction && parts.length > 2) {
    subdomain = parts[0];
  }

  // Create new headers object to pass data to our layouts
  const requestHeaders = new Headers(req.headers);

  // --- SCENARIO 1: SUBDOMAIN MODE (Prod / Localhost) ---
  if (subdomain && subdomain !== "www" && !isCodespace) {
    requestHeaders.set("x-routing-mode", "subdomain");

    const rewriteUrl = url.clone(); // Clone preserves query params (?code=xxx)

    // Prevent double-prefixing if Next.js makes an internal data fetch
    if (!url.pathname.startsWith(`/${subdomain}`)) {
      rewriteUrl.pathname = `/${subdomain}${url.pathname}`;
    }

    return NextResponse.rewrite(rewriteUrl, {
      request: { headers: requestHeaders },
    });
  }

  // --- SCENARIO 2: PATH MODE (Codespaces or naviera.com/logismart) ---
  requestHeaders.set("x-routing-mode", "path");

  // Extract the first segment (e.g., "logismart" from "/logismart/dashboard")
  const pathSegments = url.pathname.split("/").filter(Boolean);
  const possibleSlug = pathSegments[0];

  // If they hit the root (/) or a generic path without a slug (/login), force Naviera
  if (
    !possibleSlug ||
    possibleSlug === "login" ||
    possibleSlug === "dashboard"
  ) {
    const rewriteUrl = url.clone();
    rewriteUrl.pathname = `/naviera${url.pathname}`;
    return NextResponse.rewrite(rewriteUrl, {
      request: { headers: requestHeaders },
    });
  }

  // If they typed /logismart/login, let it pass through! Next.js will handle it natively.
  return NextResponse.next({
    request: { headers: requestHeaders },
  });
}
