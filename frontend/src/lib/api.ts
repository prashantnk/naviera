// frontend/src/lib/api.ts
import { Tenant } from "@/types/tenant";
import { getSupabaseClient } from "./supabase";
import { getBackendUrl } from "./config";

export async function getTenantBySlug(slug: string): Promise<Tenant | null> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    const res = await fetch(
      `${getBackendUrl()}/api/v1/tenants/${slug}/public`,
      {
        next: { revalidate: 3600 },
        signal: controller.signal,
      }
    );

    clearTimeout(timeoutId);

    // 1. Valid 404 (Workspace doesn't exist)
    if (res.status === 404) return null;

    // 2. The server is AWAKE, but broken (e.g. 500 DB Error). THROW IT!
    if (!res.ok) {
      throw new Error(`Server Error: ${res.status}`);
    }

    const tenant: Tenant = await res.json();
    return tenant;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } catch (error: any) {
    // 3. Mask only Cold Starts: AbortError (timeout) or fetch failed (Render completely down)
    if (
      error.name === "AbortError" ||
      error.message.includes("fetch failed") ||
      error.code === "ECONNREFUSED"
    ) {
      console.warn(`[Fallback] Server asleep. Returning Naviera fallback.`);
      return {
        id: "naviera-fallback-id",
        name: "Naviera",
        slug: "naviera",
        settings: {
          brand: { primary_color: "#2563eb", secondary_color: "#1e40af" },
        },
      } as Tenant;
    }

    // 4. If it failed for any other reason, LET IT THROW so the Error Boundary catches it!
    throw error;
  }
}

export async function downloadShippingLabel(
  tenantSlug: string,
  shipmentId: string,
  trackingId: string
) {
  const supabase = getSupabaseClient(tenantSlug);
  const {
    data: { session },
  } = await supabase.auth.getSession();

  // This runs on the browser, so it safely relies on the relative proxy path!
  const response = await fetch(`/api/v1/shipments/${shipmentId}/label`, {
    headers: {
      Authorization: `Bearer ${session?.access_token}`,
      "X-Tenant-Slug": tenantSlug,
    },
  });

  if (!response.ok) throw new Error("Failed to generate label");

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `Label_${trackingId}.pdf`;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}
