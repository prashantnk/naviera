// frontend/src/lib/document-storage.ts
"use client";

/**
 * Tenant-scoped access to the private Supabase `documents` bucket.
 *
 * Every object lives under `<tenant_slug>/...`; the `storage.objects` policies
 * (migration `e8f9a0b1c2d3`) only let an active member of that tenant upload or
 * read it. The bucket is private, so objects are never opened through a public
 * URL: readers always mint a short-lived signed URL from whatever reference was
 * stored (a bare object key, or an older public / authenticated / signed URL).
 */
import { useEffect, useState } from "react";

import { getSupabaseClient } from "@/lib/supabase";

export const DOCUMENTS_BUCKET = "documents";
/** Lifetime of a signed read URL; long enough to open or render once. */
export const SIGNED_URL_TTL_SECONDS = 60;

const UNSAFE_FILENAME_CHARS = /[^a-zA-Z0-9.-]/g;
const BUCKET_OBJECT_URL = /\/storage\/v1\/object\/(?:public|sign|authenticated)\/documents\/([^?#]+)/i;
const HTTP_URL = /^https?:\/\//i;
const LEADING_SLASHES = /^\/+/;
const BUCKET_PREFIX = /^documents\//;

/**
 * Builds a new object key inside the tenant's folder.
 *
 * @param tenantSlug - Tenant folder (first path segment, checked by the storage policies).
 * @param fileName - Original file name; unsafe characters become `_`.
 * @param label - Short purpose tag, e.g. `measurement` or `ndr`.
 * @param now - Timestamp for uniqueness (injectable for tests).
 * @returns `<tenant_slug>/<label>_<now>_<safe_file_name>`.
 */
export function buildDocumentObjectKey(
  tenantSlug: string,
  fileName: string,
  label: string,
  now: number = Date.now(),
): string {
  const safeName = fileName.replace(UNSAFE_FILENAME_CHARS, "_");
  return `${tenantSlug}/${label}_${now}_${safeName}`;
}

/**
 * Derives the bucket object key from a stored document reference.
 *
 * @param reference - Bare key (`logismart/x.pdf`, optionally `documents/`-prefixed) or a
 *   Supabase Storage URL for the `documents` bucket (public, authenticated or signed).
 * @returns The object key, or `null` for blanks and for URLs outside the bucket.
 */
export function documentObjectKey(reference: string): string | null {
  const trimmed = (reference || "").trim();
  if (!trimmed) return null;
  const match = trimmed.match(BUCKET_OBJECT_URL);
  if (match) {
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return null;
    }
  }
  if (HTTP_URL.test(trimmed)) return null;
  return trimmed.replace(LEADING_SLASHES, "").replace(BUCKET_PREFIX, "") || null;
}

/**
 * Stable http(s) reference for APIs that only accept URLs (measurement `evidence_urls`,
 * NDR `document_url`). It names the private object; it is not a public link, so
 * readers resolve it with {@link signDocumentUrl}.
 *
 * @param objectKey - Key returned by {@link uploadTenantDocument}.
 * @returns `<SUPABASE_URL>/storage/v1/object/authenticated/documents/<key>`.
 */
export function documentReferenceUrl(objectKey: string): string {
  const base = (process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").replace(/\/+$/, "");
  const encodedKey = objectKey.split("/").map(encodeURIComponent).join("/");
  return `${base}/storage/v1/object/authenticated/${DOCUMENTS_BUCKET}/${encodedKey}`;
}

/**
 * Uploads a file into the tenant's folder. Never overwrites (keys are unique and the
 * storage policies allow no client UPDATE).
 *
 * @param tenantSlug - Tenant whose folder receives the file.
 * @param file - File chosen by the user.
 * @param label - Short purpose tag for the key.
 * @returns The stored object key.
 */
export async function uploadTenantDocument(tenantSlug: string, file: File, label: string): Promise<string> {
  const objectKey = buildDocumentObjectKey(tenantSlug, file.name, label);
  const { error } = await getSupabaseClient(tenantSlug).storage.from(DOCUMENTS_BUCKET).upload(objectKey, file);
  if (error) throw error;
  return objectKey;
}

/**
 * Resolves a stored reference into a URL the browser can load.
 *
 * @param tenantSlug - Tenant whose Supabase session signs the URL.
 * @param reference - Stored key or URL (see {@link documentObjectKey}).
 * @returns A short-lived signed URL for bucket objects, the reference itself for
 *   URLs outside the bucket, or `null` when it cannot be resolved (missing, or the
 *   caller's tenant does not own the object).
 */
export async function signDocumentUrl(tenantSlug: string, reference: string): Promise<string | null> {
  const objectKey = documentObjectKey(reference);
  if (!objectKey) {
    const trimmed = (reference || "").trim();
    return HTTP_URL.test(trimmed) ? trimmed : null;
  }
  const { data, error } = await getSupabaseClient(tenantSlug)
    .storage.from(DOCUMENTS_BUCKET)
    .createSignedUrl(objectKey, SIGNED_URL_TTL_SECONDS);
  return !error && data?.signedUrl ? data.signedUrl : null;
}

/**
 * Opens a stored document in a new tab through a signed URL.
 *
 * @param tenantSlug - Tenant whose session signs the URL.
 * @param reference - Stored key or URL.
 * @returns `false` when the document could not be resolved.
 */
export async function openDocument(tenantSlug: string, reference: string): Promise<boolean> {
  const url = await signDocumentUrl(tenantSlug, reference);
  if (!url) return false;
  window.open(url, "_blank", "noopener,noreferrer");
  return true;
}

/**
 * Signed URL for rendering a stored document (e.g. an `<img>`), refreshed when the
 * reference changes.
 *
 * @param tenantSlug - Tenant whose session signs the URL.
 * @param reference - Stored key or URL; falsy means nothing to show.
 * @returns The resolved URL, or `null` while loading / when unavailable.
 */
export function useSignedDocumentUrl(tenantSlug: string, reference: string | null | undefined): string | null {
  const [resolved, setResolved] = useState<{ reference: string; url: string | null } | null>(null);
  useEffect(() => {
    if (!reference || !tenantSlug) return;
    let cancelled = false;
    signDocumentUrl(tenantSlug, reference)
      .catch(() => null)
      .then((url) => {
        if (!cancelled) setResolved({ reference, url });
      });
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, reference]);
  return reference && resolved?.reference === reference ? resolved.url : null;
}
