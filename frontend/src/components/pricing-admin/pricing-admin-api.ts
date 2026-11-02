// frontend/src/components/pricing-admin/pricing-admin-api.ts
/**
 * Thin typed adapter over the staff-only pricing endpoints (API_CONTRACT.md §6 + §7):
 *   GET/PUT  /api/v1/pricing/policy                      (staff read; owner/admin write)
 *   (`GET /api/v1/pricing/prime-zones` is not needed until the zones editor exists.)
 *   GET      /api/v1/pricing/prime-lanes?active_only=    (staff read)
 *   PATCH    /api/v1/pricing/prime-lanes/{id}            (owner/admin)
 *   POST     /api/v1/pricing/prime-lanes/import?dry_run= (owner/admin, multipart `file`)
 *   GET      /api/v1/pricing/prime-lanes/export.csv      (staff read)
 *
 * The generated client does not have these endpoints yet, so the interfaces below
 * mirror the backend contract field-for-field. When `src/api_client` is regenerated,
 * swap these local types for the generated ones and keep the function names, so the
 * UI components do not change.
 *
 * Every number is passed through exactly as the backend sent it (Zero Frontend Math).
 *
 * Spring analogy: a `@Component` facade around a Feign client.
 */
import {
  MarkupMode,
  OpenAPI,
  PricingService,
  PrimeRatesService,
  ServiceOption,
  type OptionMarkup,
  type PricingPolicy,
  type PricingPolicyRead,
} from "@/api_client";
import axios from "axios";

export { MarkupMode, ServiceOption };
export type { OptionMarkup, PricingPolicy, PricingPolicyRead };

/** Every option, in the order the admin sees the toggles and markup rows. */
export const ALL_SERVICE_OPTIONS: readonly ServiceOption[] = [
  ServiceOption.DELHIVERY_SURFACE,
  ServiceOption.DELHIVERY_EXPRESS,
  ServiceOption.DELHIVERY_B2B_SURFACE,
  ServiceOption.PRIME_SURFACE,
];

/** One Prime lane (`PrimeLaneRead`). `transporter_name` is staff-only internal data. */
export interface PrimeLaneRead {
  id: string;
  origin_zone: string;
  dest_zone: string;
  mode: string;
  transporter_name: string;
  tat_hours: number;
  rate_per_kg: number;
  min_lr_charge: number;
  docket_charge: number;
  min_chargeable_kg: number;
  volumetric_divisor: number;
  max_dimension_cm: number;
  delivery_type: string;
  oda_per_kg: number;
  oda_min: number;
  odd_weight_per_kg: number;
  odd_weight_min: number;
  pickup_per_kg: number;
  pickup_min: number;
  door_delivery_per_kg: number;
  door_delivery_min: number;
  markup_percent: number;
  is_active: boolean;
  updated_at: string;
}

/** Fields the inline editor may PATCH (any subset). */
export interface PrimeLanePatch {
  tat_hours?: number;
  rate_per_kg?: number;
  min_lr_charge?: number;
  docket_charge?: number;
  markup_percent?: number;
  is_active?: boolean;
}

/** One problem the CSV importer found (`row` is the CSV line, when known). */
export interface PrimeImportIssue {
  row: number | null;
  message: string;
}

/** CSV import result (`PrimeImportReport`), for both dry runs and real imports. */
export interface PrimeImportReport {
  created: number;
  updated: number;
  deactivated: number;
  errors: PrimeImportIssue[];
  warnings: PrimeImportIssue[];
}

const EXPORT_URL = "/api/v1/pricing/prime-lanes/export.csv";
const EXPORT_FILENAME = "prime-lanes.csv";
const TEMPLATE_URL = "/api/v1/pricing/prime-lanes/template.csv";
const TEMPLATE_FILENAME = "prime_lanes_template.csv";
const CSV_MIME_TYPE = "text/csv";

/**
 * Loads the tenant's pricing policy using the generated client.
 *
 * @param tenantSlug - Tenant slug header.
 * @returns The policy plus the backend-computed `cod_enabled` / `delhivery_configured`.
 */
export function fetchPricingPolicy(tenantSlug?: string | null): Promise<PricingPolicyRead> {
  return PricingService.getPricingPolicy(tenantSlug);
}

/**
 * Saves the pricing policy using the generated client (owner/admin only; the backend returns 403 otherwise).
 *
 * @param policy - The full policy to store.
 * @param tenantSlug - Tenant slug header.
 * @returns The saved policy as the backend now sees it.
 */
export function updatePricingPolicy(
  policy: PricingPolicy,
  tenantSlug?: string | null,
): Promise<PricingPolicyRead> {
  return PricingService.replacePricingPolicy(policy, tenantSlug);
}

/**
 * Lists Prime lanes using the generated `PrimeRatesService`.
 *
 * @param activeOnly - When true, only lanes customers can currently book.
 * @param tenantSlug - Tenant slug header.
 * @returns Lanes as stored on the server.
 */
export function fetchPrimeLanes(
  activeOnly: boolean,
  tenantSlug?: string | null,
): Promise<PrimeLaneRead[]> {
  return PrimeRatesService.listPrimeLanes(activeOnly, tenantSlug);
}

/**
 * Updates some fields of one Prime lane using the generated `PrimeRatesService`.
 *
 * @param laneId - Lane UUID.
 * @param patch - Only the fields that changed.
 * @param tenantSlug - Tenant slug header.
 * @returns The updated lane.
 */
export function patchPrimeLane(
  laneId: string,
  patch: PrimeLanePatch,
  tenantSlug?: string | null,
): Promise<PrimeLaneRead> {
  return PrimeRatesService.updatePrimeLane(laneId, patch, tenantSlug);
}

/**
 * Uploads a lanes CSV using the generated `PrimeRatesService`. With `dryRun` the server only reports what would change.
 *
 * @param file - CSV in the export format.
 * @param dryRun - True for the preview, false to apply.
 * @param tenantSlug - Tenant slug header.
 * @returns Counts of created / updated / deactivated lanes plus row errors and warnings.
 */
export function importPrimeLanes(
  file: Blob,
  dryRun: boolean,
  tenantSlug?: string | null,
): Promise<PrimeImportReport> {
  return PrimeRatesService.importPrimeLanes(
    file,
    dryRun,
    tenantSlug,
  ) as unknown as Promise<PrimeImportReport>;
}

/**
 * Resolves the generated client's headers (JWT + `X-Tenant-Slug`) for a raw axios call.
 *
 * @param url - Endpoint being called (passed to header resolvers).
 * @returns Header map for axios.
 */
async function _resolveHeaders(url: string): Promise<Record<string, string>> {
  const resolver = OpenAPI.HEADERS;
  if (typeof resolver === "function") {
    return resolver({ method: "GET", url });
  }
  return resolver || {};
}

/**
 * Downloads every lane as CSV (the same format the importer accepts).
 *
 * The generated client cannot request a blob, so this reuses its auth headers on a raw
 * axios call (same approach as `components/pickups/pickup-downloads.ts`).
 */
export async function downloadPrimeLanesCsv(): Promise<void> {
  const headers = await _resolveHeaders(EXPORT_URL);
  const response = await axios.get(EXPORT_URL, { headers, responseType: "blob" });
  const blob = new Blob([response.data], { type: CSV_MIME_TYPE });
  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = EXPORT_FILENAME;
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(objectUrl);
  document.body.removeChild(anchor);
}

/**
 * Downloads the sample Prime lanes CSV template (exact header columns + 2 realistic sample rows).
 */
export async function downloadPrimeLanesTemplateCsv(): Promise<void> {
  const headers = await _resolveHeaders(TEMPLATE_URL);
  const response = await axios.get(TEMPLATE_URL, { headers, responseType: "blob" });
  const blob = new Blob([response.data], { type: CSV_MIME_TYPE });
  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = TEMPLATE_FILENAME;
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(objectUrl);
  document.body.removeChild(anchor);
}
