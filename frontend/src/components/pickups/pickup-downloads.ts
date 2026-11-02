// frontend/src/components/pickups/pickup-downloads.ts
/**
 * Authenticated PDF downloads for Pickup Requests ("Print label" and
 * "Manifest Copy").
 *
 * The generated OpenAPI client cannot request `responseType: "blob"`, so these
 * helpers reuse the client's resolved auth + tenant headers and call axios
 * directly (same approach as `lib/api.ts`).
 */
import { OpenAPI } from "@/api_client";
import axios from "axios";

import { getPickupDisplayId, PickupLabelFormat } from "./pickup-constants";

const PDF_MIME_TYPE = "application/pdf";
const MANIFESTS_ENDPOINT = "/api/v1/manifests";
const THERMAL_FILENAME_SUFFIX = "_Thermal4x2";

/** Minimal manifest shape needed to build download URLs and file names. */
interface DownloadableManifest {
  id: string;
  pickup_request_number?: string | null;
}

/**
 * Resolves the OpenAPI client's headers (JWT + `X-Tenant-Slug`).
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
 * Downloads a PDF from an authenticated endpoint and saves it under `filename`.
 *
 * @param url - API path, e.g. `/api/v1/manifests/{id}/pdf`.
 * @param filename - Suggested file name for the browser download.
 * @param params - Optional query parameters.
 */
async function _downloadPdf(
  url: string,
  filename: string,
  params?: Record<string, string>
): Promise<void> {
  const headers = await _resolveHeaders(url);
  const response = await axios.get(url, { headers, params, responseType: "blob" });
  const blob = new Blob([response.data], { type: PDF_MIME_TYPE });
  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(objectUrl);
  document.body.removeChild(anchor);
}

/**
 * "Print label": one merged PDF with the labels of every shipment in the pickup.
 *
 * @param manifest - Pickup Request to print.
 * @param labelFormat - A4 sheet or 4x2 thermal labels.
 */
export async function downloadPickupLabels(
  manifest: DownloadableManifest,
  labelFormat: PickupLabelFormat = PickupLabelFormat.A4
): Promise<void> {
  const suffix = labelFormat === PickupLabelFormat.THERMAL_4X2 ? THERMAL_FILENAME_SUFFIX : "";
  await _downloadPdf(
    `${MANIFESTS_ENDPOINT}/${manifest.id}/labels`,
    `PUR_${getPickupDisplayId(manifest)}_Labels${suffix}.pdf`,
    { label_format: labelFormat }
  );
}

/**
 * "Manifest Copy" / driver run-sheet PDF of what is (or was) handed over.
 *
 * @param manifest - Pickup Request to download.
 */
export async function downloadPickupManifestCopy(manifest: DownloadableManifest): Promise<void> {
  await _downloadPdf(
    `${MANIFESTS_ENDPOINT}/${manifest.id}/pdf`,
    `PUR_${getPickupDisplayId(manifest)}_Manifest.pdf`
  );
}
