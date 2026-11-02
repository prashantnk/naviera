// frontend/src/lib/download-blob.ts
/**
 * Saves a downloaded Blob (label, run-sheet, invoice, CSV) as a file in a way that also
 * works on iOS Safari and in WhatsApp / Gmail / Instagram in-app browsers (E-13).
 *
 * Two fixes over the classic "anchor click + revokeObjectURL":
 * 1. The object URL is revoked only after a delay. Revoking it straight after `click()`
 *    cancels the download on iOS Safari, which reads the blob asynchronously.
 * 2. In-app browsers ignore the `download` attribute, so there the blob is opened in a
 *    new tab/view instead (the PDF viewer then offers Share / Save / Print).
 *
 * Spring Boot analogy: a small `@Component` utility; there is no server-side equivalent
 * because the browser decides how a file is saved.
 */

/** How long the object URL stays valid after the download starts (ms). */
export const OBJECT_URL_REVOKE_DELAY_MS = 60_000;

/** User-agent markers of embedded (in-app) browsers that ignore `<a download>`. */
const IN_APP_BROWSER_PATTERN =
  /(FBAN|FBAV|Instagram|WhatsApp|GSA\/|Line\/|; wv\)|GmailApp|Gmail)/i;

/**
 * Whether the user agent is an in-app browser that ignores the `download` attribute.
 *
 * @param userAgent - `navigator.userAgent` (injectable for tests).
 * @returns True for WhatsApp, Gmail, Instagram, Facebook, Google app and Android WebViews.
 */
export function isInAppBrowser(userAgent: string): boolean {
  return IN_APP_BROWSER_PATTERN.test(userAgent);
}

/**
 * Opens the object URL in a new view; falls back to the current tab when pop-ups are blocked.
 *
 * @param url - The blob object URL.
 */
function _openInNewView(url: string): void {
  const opened = window.open(url, "_blank", "noopener");
  if (!opened) {
    window.location.assign(url);
  }
}

/**
 * Clicks a temporary `<a download>` link for the object URL.
 *
 * @param url - The blob object URL.
 * @param filename - Suggested file name.
 */
function _clickDownloadLink(url: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

/**
 * Saves `blob` as `filename`, revoking the object URL only after the browser had time to read it.
 *
 * @param blob - File contents returned by the API.
 * @param filename - Suggested file name, e.g. `Label_LOGISMART-1234.pdf`.
 */
export function saveBlobAsFile(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  if (isInAppBrowser(window.navigator.userAgent)) {
    _openInNewView(url);
  } else {
    _clickDownloadLink(url, filename);
  }
  window.setTimeout(() => window.URL.revokeObjectURL(url), OBJECT_URL_REVOKE_DELAY_MS);
}
