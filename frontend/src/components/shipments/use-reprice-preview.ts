// frontend/src/components/shipments/use-reprice-preview.ts
"use client";

/**
 * React hook that fetches the server re-price preview for a pending change.
 *
 * The change object is serialised to a stable key, so the request re-runs only when the
 * change really differs, and it is debounced so typing a COD amount does not flood the
 * API. Stale responses are ignored (a newer request always wins).
 *
 * Spring analogy: a cached `@Service` call keyed by the request DTO.
 */
import { useEffect, useState } from "react";

import type { PickupUpdate } from "@/api_client";
import { extractApiErrorMessage } from "@/lib/utils";

import { fetchRepricePreview, type RepricePreview } from "./reprice-api";

/** Default debounce before calling the preview endpoint. */
export const PREVIEW_DEBOUNCE_MS = 400;

/** Options of {@link useRepricePreview}. */
export interface UseRepricePreviewOptions {
  /** Skip the request (e.g. dialog closed or the change is incomplete). */
  enabled?: boolean;
  debounceMs?: number;
}

/** State returned by {@link useRepricePreview}. */
export interface RepricePreviewState {
  preview: RepricePreview | null;
  loading: boolean;
  error: string | null;
}

const IDLE_STATE: RepricePreviewState = { preview: null, loading: false, error: null };

/**
 * Fetches `POST /shipments/{id}/reprice-preview` for `change`.
 *
 * @param shipmentId - Shipment UUID.
 * @param change - Changed fields only; null disables the request.
 * @param tenantSlug - Tenant slug header.
 * @param options - Enable flag and debounce.
 * @returns The latest preview, loading flag and error text.
 */
export function useRepricePreview(
  shipmentId: string | null | undefined,
  change: PickupUpdate | null,
  tenantSlug: string | null | undefined,
  options: UseRepricePreviewOptions = {},
): RepricePreviewState {
  const { enabled = true, debounceMs = PREVIEW_DEBOUNCE_MS } = options;
  const changeKey = change ? JSON.stringify(change) : null;
  const [state, setState] = useState<RepricePreviewState>(IDLE_STATE);

  useEffect(() => {
    if (!enabled || !shipmentId || changeKey === null) {
      setState(IDLE_STATE);
      return;
    }
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    const timer = setTimeout(() => {
      fetchRepricePreview(shipmentId, JSON.parse(changeKey) as PickupUpdate, tenantSlug)
        .then((preview) => {
          if (!cancelled) setState({ preview, loading: false, error: null });
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setState({
              preview: null,
              loading: false,
              error: extractApiErrorMessage(err, "Could not check the revised charges."),
            });
          }
        });
    }, debounceMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [enabled, shipmentId, changeKey, tenantSlug, debounceMs]);

  return state;
}
