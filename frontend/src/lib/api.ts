// frontend/src/lib/api.ts
import { Tenant } from "@/types/tenant";
import { getSupabaseClient } from "./supabase";
import { getBackendUrl } from "./config";
import { saveBlobAsFile } from "./download-blob";

/** How long the tenant-config request may take before the page shows an error. */
const TENANT_CONFIG_TIMEOUT_MS = 10000;

/**
 * Valid tenant slugs consist strictly of ASCII letters, digits, and internal hyphens
 * (e.g. `logismart`, `logismart-test`, `naviera`). Any top-level path segment containing
 * punctuation, dots, or URL-encoded characters (`$`, `%24`, `favicon.ico`, `favicon.png`)
 * is rejected immediately on the server without querying the backend API.
 */
const VALID_TENANT_SLUG_REGEX = /^[a-z0-9]+(?:-[a-z0-9]+)*$/i;

export function isValidTenantSlug(slug: string): boolean {
  const normalized = slug.trim();
  return Boolean(normalized) && normalized.length <= 64 && VALID_TENANT_SLUG_REGEX.test(normalized);
}

/**
 * Thrown when the tenant config cannot be loaded because the backend is slow
 * or unreachable (cold start, deploy, network). The error boundary shows a
 * neutral "try again" page; we NEVER render another tenant's site instead (F-12).
 */
export class TenantUnavailableError extends Error {
  constructor(slug: string, cause?: unknown) {
    super(`Workspace configuration for "${slug}" is temporarily unavailable.`);
    this.name = "TenantUnavailableError";
    this.cause = cause;
  }
}

/**
 * Whether a fetch failure means "backend not reachable / too slow" rather
 * than a real application error.
 *
 * @param error - What `fetch` threw.
 * @returns True for timeouts (AbortError), "fetch failed" and refused connections.
 */
function _isBackendUnreachable(error: unknown): boolean {
  const err = error as { name?: string; message?: string; code?: string };
  return (
    err?.name === "AbortError" ||
    Boolean(err?.message && err.message.includes("fetch failed")) ||
    err?.code === "ECONNREFUSED"
  );
}

export async function getTenantBySlug(slug: string): Promise<Tenant | null> {
  if (!isValidTenantSlug(slug)) {
    return null;
  }
  const normalizedSlug = slug.trim().toLowerCase();

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), TENANT_CONFIG_TIMEOUT_MS);

    const res = await fetch(
      `${getBackendUrl()}/api/v1/tenants/${encodeURIComponent(normalizedSlug)}/public`,
      {
        next: { revalidate: 3600, tags: [`tenant-${normalizedSlug}`] },
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
  } catch (error: unknown) {
    // 3. Slow / unreachable backend: log it and let the error boundary show a
    //    neutral retry page. Never substitute another tenant's branding.
    if (_isBackendUnreachable(error)) {
      console.error(`[tenant-config] backend unreachable for slug "${slug}"`, error);
      throw new TenantUnavailableError(slug, error);
    }

    // 4. If it failed for any other reason, LET IT THROW so the Error Boundary catches it!
    console.error(`[tenant-config] failed to load slug "${slug}"`, error);
    throw error;
  }
}

export async function downloadShippingLabel(
  tenantSlug: string,
  shipmentId: string,
  trackingId: string,
  labelFormat: "a4" | "thermal_4x2" = "a4"
) {
  const supabase = getSupabaseClient(tenantSlug);
  const {
    data: { session },
  } = await supabase.auth.getSession();

  // This runs on the browser, so it safely relies on the relative proxy path!
  const response = await fetch(
    `/api/v1/shipments/${shipmentId}/label?label_format=${labelFormat}`,
    {
      headers: {
        Authorization: `Bearer ${session?.access_token}`,
        "X-Tenant-Slug": tenantSlug,
      },
    }
  );

  if (!response.ok) throw new Error("Failed to generate label");

  const blob = await response.blob();
  const suffix = labelFormat === "thermal_4x2" ? "_Thermal4x2" : "";
  saveBlobAsFile(blob, `Label_${trackingId}${suffix}.pdf`);
}

async function downloadAuthenticatedBlob(
  endpointUrl: string,
  defaultFilename: string,
  params?: Record<string, string | boolean | undefined>
): Promise<void> {
  const { OpenAPI } = await import("@/api_client");
  const axios = (await import("axios")).default;

  const headers =
    typeof OpenAPI.HEADERS === "function"
      ? await OpenAPI.HEADERS({ method: "GET", url: endpointUrl })
      : OpenAPI.HEADERS || {};

  const response = await axios.get(endpointUrl, {
    headers,
    params,
    responseType: "blob",
  });

  const blob = new Blob([response.data], {
    type: String(response.headers["content-type"] || "application/octet-stream"),
  });
  saveBlobAsFile(blob, defaultFilename);
}

export async function downloadWalletReceiptPdf(
  txnId: string,
  receiptNumber?: string
): Promise<void> {
  const safeName = receiptNumber || txnId.slice(0, 8).toUpperCase();
  await downloadAuthenticatedBlob(
    `/api/v1/wallet/transactions/${txnId}/receipt-pdf`,
    `Receipt_${safeName}.pdf`
  );
}

export async function downloadShipmentInvoicePdf(
  shipmentId: string,
  trackingId?: string | null
): Promise<void> {
  const safeName = trackingId || shipmentId.slice(0, 8).toUpperCase();
  await downloadAuthenticatedBlob(
    `/api/v1/shipments/${shipmentId}/invoice-pdf`,
    `GST_Invoice_${safeName}.pdf`
  );
}

export async function downloadManifestRunsheetPdf(
  manifestId: string
): Promise<void> {
  const safeName = manifestId.slice(0, 8).toUpperCase();
  await downloadAuthenticatedBlob(
    `/api/v1/manifests/${manifestId}/pdf`,
    `RunSheet_${safeName}.pdf`
  );
}

export async function downloadShipmentsCsv(isB2b?: boolean): Promise<void> {
  const prefix = isB2b ? "B2B_Cargo_Shipments" : "B2C_Shipments";
  await downloadAuthenticatedBlob(
    `/api/v1/shipments/export/csv`,
    `${prefix}_Export.csv`,
    isB2b !== undefined ? { is_b2b: isB2b } : undefined
  );
}

/**
 * Downloads the wallet ledger CSV. Owner / Admin / Read-Only staff get the
 * tenant-wide ledger unless `userId` narrows it to one user.
 *
 * @param userId - Optional wallet owner to export (staff finance viewers only).
 */
export async function downloadWalletLedgerCsv(userId?: string): Promise<void> {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  await downloadAuthenticatedBlob(
    `/api/v1/wallet/export/csv${query}`,
    `Unified_Wallet_Ledger.csv`
  );
}

