// src/lib/api.ts
import { Tenant } from "@/types/tenant";

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