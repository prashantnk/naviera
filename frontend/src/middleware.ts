// src/middleware.ts
import { APP_CONFIG } from "@/lib/config";
import { NextRequest, NextResponse } from "next/server";

export const config = {
  matcher: [
    // Added a regex group at the end to ignore all common image files
    "/((?!api|_next/static|_next/image|favicon.ico|health|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};

export default function middleware(req: NextRequest) {
  const url = req.nextUrl;
  let hostname = req.headers.get("host") || "";
  hostname = hostname.replace(":.+", "");

  const isLocal = hostname.includes(APP_CONFIG.DOMAINS.LOCALHOST);
  const isCodespace = hostname.includes(APP_CONFIG.DOMAINS.CODESPACE_SUFFIX);
  const isProduction = hostname.includes(APP_CONFIG.DOMAINS.PRODUCTION);

  let subdomain = "";
  const parts = hostname.split(".");

  if (isLocal && parts.length > 1) {
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
