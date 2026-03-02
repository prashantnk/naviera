// frontend/next.config.ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This tells Next.js to act as a Proxy for our Backend
  async rewrites() {
    const supabaseUrl =
      process.env.NEXT_PUBLIC_SUPABASE_URL?.replace(/\/$/, "") || "";
    return [
      {
        // Any request coming to the frontend starting with /api/
        source: "/api/:path*",
        // Will be secretly forwarded to FastAPI on the local container network!
        destination: "http://127.0.0.1:8000/api/:path*",
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
