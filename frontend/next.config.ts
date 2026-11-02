// frontend/next.config.ts
import type { NextConfig } from "next";

const BACKEND_PROXY_TIMEOUT_MS = 120_000;

/** B-11 (A6-21): no clickjacking (no framing by other sites), no MIME sniffing. */
const SECURITY_HEADERS = [
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  // Dev-only: hosts allowed to load /_next dev resources (GitHub Codespaces port
  // forwarding + local). Add your own remote dev host here if you use one.
  allowedDevOrigins: [
    "**.app.github.dev",
    "localhost",
    "**.localhost",
    "127.0.0.1",
  ],
  experimental: {
    // The /api rewrite below proxies to FastAPI with a 30 s default timeout. Money writes
    // (e.g. pickup dispatch with actual pieces = re-price + GST note + wallet) make many
    // DB round trips; from a dev box far from the Supabase region they can exceed 30 s,
    // and the proxy would then drop a request the backend still commits.
    proxyTimeout: BACKEND_PROXY_TIMEOUT_MS,
  },
  // This tells Next.js to act as a Proxy for our Backend
  async rewrites() {
    const supabaseUrl =
      process.env.NEXT_PUBLIC_SUPABASE_URL?.replace(/\/$/, "") || "";
      
    // 🔥 NEW: Dynamically point to Render in Prod, or localhost in Dev
    const backendUrl = 
      process.env.BACKEND_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

    return [
      {
        // Any request coming to the frontend starting with /api/
        source: "/api/:path*",
        // Will be secretly forwarded to FastAPI!
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${backendUrl}/health`,
      },
      {
        // Supabase ISP Block Bypass Proxy
        source: "/supabase-proxy/:path*",
        destination: `${supabaseUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;