// src/lib/api.ts
import { Tenant } from "@/types/tenant";
import { getSupabaseClient } from "./supabase";

const BASE_URL = "http://127.0.0.1:8000/api/v1";

export async function getTenantBySlug(slug: string): Promise<Tenant | null> {
  try {
    const res = await fetch(`${BASE_URL}/tenants/${slug}/public`, {
      cache: "no-store",
    });

    if (!res.ok) {
      throw new Error(`Backend responded with status: ${res.status}`);
    }

    // We cast the JSON response to our strict TypeScript interface
    const tenant: Tenant = await res.json();
    return tenant;
  } catch (error) {
    console.error("API Error fetching tenant:", error);
    return null;
  }
}
export async function downloadShippingLabel(
  tenantSlug: string,
  shipmentId: string,
  trackingId: string,
) {
  const supabase = getSupabaseClient(tenantSlug);
  const {
    data: { session },
  } = await supabase.auth.getSession();

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
