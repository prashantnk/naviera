// src/lib/config.ts

export const APP_CONFIG = {
  name: "Naviera",
  description: "Multi-tenant Logistics SaaS",

  // The cookie or header key we use to pass tenant info
  HEADERS: {
    TENANT_SLUG: "x-tenant-slug",
    AUTH_TOKEN: "Authorization",
  },

  // Routing Constants
  ROUTES: {
    HOME: "/",
    LOGIN: "/login",
    DASHBOARD: "/dashboard",
  },

  // Environment-specific domains
  DOMAINS: {
    PRODUCTION: "naviera.com",
    LOCALHOST: "localhost",
    // This is the suffix Codespaces uses.
    // It usually looks like: ...app.github.dev
    CODESPACE_SUFFIX: ".app.github.dev",
  },
} as const;

export function getBackendUrl() {
  return (
    process.env.BACKEND_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000"
  );
}
