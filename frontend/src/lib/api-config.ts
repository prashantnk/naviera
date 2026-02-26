// src/lib/api-config.ts
import { OpenAPI } from "@/api_client";
import { getSupabaseClient } from "./supabase";

/**
 * Configures the auto-generated OpenAPI client with our multi-tenant auth.
 * We call this function before making API requests from the frontend.
 */
export function configureApiClient(tenantSlug: string) {
  // 1. Point it to the Next.js Proxy (which routes to FastAPI)
  OpenAPI.BASE = "";

  // 2. Dynamically inject headers for every request
  OpenAPI.HEADERS = async () => {
    const supabase = getSupabaseClient(tenantSlug);
    const {
      data: { session },
    } = await supabase.auth.getSession();

    return {
      "X-Tenant-Slug": tenantSlug,
      ...(session?.access_token
        ? { Authorization: `Bearer ${session.access_token}` }
        : {}),
    };
  };
}
