// src/middleware.ts
import { APP_CONFIG } from "@/lib/config";
import { NextRequest, NextResponse } from "next/server";

export const config = {
  // Matcher: Filters which paths this middleware runs on.
  // We exclude static files (images, fonts) and internal Next.js files (_next).
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};

export default async function middleware(req: NextRequest) {
  const url = req.nextUrl;

  // 1. Get Hostname (e.g. "logismart.naviera.com" or "logismart.localhost:3000")
  let hostname = req.headers.get("host")!;

  // Handle local development where host includes port (remove :3000)
  hostname = hostname.replace(":.+", "");

  // 2. Identify the Environment
  const isLocal = hostname.includes(APP_CONFIG.DOMAINS.LOCALHOST);
  const isCodespace = hostname.includes(APP_CONFIG.DOMAINS.CODESPACE_SUFFIX);
  const isProduction = hostname.includes(APP_CONFIG.DOMAINS.PRODUCTION);

  // 3. Extract Subdomain Logic
  const parts = hostname.split(".");
  let subdomain = "";

  if (isLocal) {
    // Logic for Localhost:
    // "localhost" -> parts = ["localhost"] -> No subdomain
    // "logismart.localhost" -> parts = ["logismart", "localhost"] -> subdomain = "logismart"
    if (parts.length > 1) {
      subdomain = parts[0];
    }
  } else if (isProduction) {
    // Logic for Production:
    // "naviera.com" -> parts = ["naviera", "com"] -> No subdomain
    // "logismart.naviera.com" -> parts = ["logismart", "naviera", "com"] -> subdomain = "logismart"
    if (parts.length > 2) {
      subdomain = parts[0];
    }
  } else if (isCodespace) {
    // Logic for Codespaces:
    // Codespace URLs are messy (e.g. potential-fiesta-...-3000.app.github.dev).
    // They don't support subdomains easily.
    // For now, in Codespaces, we will NOT use subdomains to avoid breaking the URL.
    // We will treat the Codespace URL as the "Main Domain".
    subdomain = "";
  }

  // --- ROUTING LOGIC ---

  // SCENARIO A: We have a valid Tenant Subdomain
  // Example: logismart.naviera.com (User sees this)
  // Rewrite to: /app/logismart/dashboard (Next.js serves this)
  if (subdomain && subdomain !== "www") {
    // We rewrite the URL path to include the dynamic segment
    return NextResponse.rewrite(
      new URL(`/app/${subdomain}${url.pathname}`, req.url),
    );
  }

  // SCENARIO B: No subdomain (Main Domain)
  // User visits: naviera.com or localhost:3000
  // Next.js serves the Root Group `(marketing)` automatically.
  return NextResponse.next();
}
