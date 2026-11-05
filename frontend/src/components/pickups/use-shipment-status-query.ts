// frontend/src/components/pickups/use-shipment-status-query.ts
"use client";

/**
 * URL-backed shipment status filter for the Shipments lists.
 *
 * `?status=OPEN` or `?status=IN_TRANSIT,EXCEPTION` (comma-separated
 * `PickupStatus` values) preselects the filter so dashboard tiles can
 * deep-link. The URL is the single source of truth: reading derives the
 * filter, writing replaces the query string (no extra history entries).
 *
 * Must be used inside `<Suspense>` because it reads `useSearchParams`.
 */
import { PickupStatus } from "@/api_client";
import { ALL_FILTER_VALUE } from "@/lib/form-options";
import { usePathname, useSearchParams } from "next/navigation";
import { useProgressRouter } from "@/hooks/use-progress-router";
import { useCallback, useMemo } from "react";

/** Query parameter name used by dashboard deep links. */
export const SHIPMENT_STATUS_QUERY_PARAM = "status";
const STATUS_SEPARATOR = ",";
const VALID_STATUSES: ReadonlySet<string> = new Set(Object.values(PickupStatus));

/**
 * Parses `?status=` into valid `PickupStatus` values (unknown values are dropped).
 *
 * @param raw - Raw query value, e.g. "IN_TRANSIT,EXCEPTION".
 * @returns Valid statuses in URL order (empty when absent or all invalid).
 */
export function parseShipmentStatusParam(raw: string | null): PickupStatus[] {
  if (!raw) return [];
  return raw
    .split(STATUS_SEPARATOR)
    .map((value) => value.trim().toUpperCase())
    .filter((value, index, all) => VALID_STATUSES.has(value) && all.indexOf(value) === index)
    .map((value) => value as PickupStatus);
}

/** Result of `useShipmentStatusQuery`. */
export interface ShipmentStatusQuery {
  /** Select value: a single status, the joined list, or `ALL`. */
  statusFilter: string;
  /** Statuses to match; empty means "all statuses". */
  statuses: ReadonlySet<PickupStatus>;
  /** True when the URL carries more than one status. */
  isMultiStatus: boolean;
  /** Writes the filter back to the URL (`ALL` removes the param). */
  setStatusFilter: (value: string) => void;
}

/**
 * Reads and writes the `?status=` filter of the current Shipments page.
 *
 * @returns Current filter state and a setter that keeps the URL in sync.
 */
export function useShipmentStatusQuery(): ShipmentStatusQuery {
  const router = useProgressRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const rawStatus = searchParams.get(SHIPMENT_STATUS_QUERY_PARAM);

  const parsed = useMemo(() => parseShipmentStatusParam(rawStatus), [rawStatus]);

  const setStatusFilter = useCallback(
    (value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (!value || value === ALL_FILTER_VALUE) params.delete(SHIPMENT_STATUS_QUERY_PARAM);
      else params.set(SHIPMENT_STATUS_QUERY_PARAM, value);
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams]
  );

  return {
    statusFilter: parsed.length === 0 ? ALL_FILTER_VALUE : parsed.join(STATUS_SEPARATOR),
    statuses: new Set(parsed),
    isMultiStatus: parsed.length > 1,
    setStatusFilter,
  };
}
