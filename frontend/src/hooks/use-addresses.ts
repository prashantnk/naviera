"use client";

import { AddressesService, type AddressRead } from "@/api_client";
import {
  buildQueryCacheKey,
  fetchWithCache,
  getCachedQuery,
  hasCachedQuery,
  invalidateQueryCache,
  setCachedQuery,
} from "@/lib/query-cache";
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

const ADDRESSES_ENDPOINT_KEY = "saved-addresses";

/**
 * Builds the canonical SWR cache key for a tenant's saved Address Book.
 *
 * @param tenantSlug - Active tenant slug.
 * @returns Deterministic cache key string.
 */
export function buildAddressesCacheKey(tenantSlug: string): string {
  return buildQueryCacheKey(tenantSlug, "session", ADDRESSES_ENDPOINT_KEY);
}

/**
 * Reads cached saved addresses synchronously (for `useState` initialization).
 *
 * @param tenantSlug - Active tenant slug.
 * @returns Cached `AddressRead[]` or `null` when cold/expired.
 */
export function getCachedAddresses(tenantSlug: string): AddressRead[] | null {
  return getCachedQuery<AddressRead[]>(buildAddressesCacheKey(tenantSlug));
}

/**
 * Returns true when non-expired saved addresses are cached for `tenantSlug`.
 */
export function hasCachedAddresses(tenantSlug: string): boolean {
  return hasCachedQuery(buildAddressesCacheKey(tenantSlug));
}

/**
 * Stores saved addresses in the SWR cache.
 */
export function setCachedAddresses(
  tenantSlug: string,
  addresses: AddressRead[],
): AddressRead[] {
  return setCachedQuery(buildAddressesCacheKey(tenantSlug), addresses);
}

/**
 * Invalidates cached saved addresses for a specific tenant or globally.
 */
export function invalidateAddressesCache(tenantSlug?: string): void {
  if (tenantSlug && tenantSlug.trim()) {
    invalidateQueryCache(buildAddressesCacheKey(tenantSlug));
    return;
  }
  invalidateQueryCache(ADDRESSES_ENDPOINT_KEY);
}

/**
 * Fetches saved addresses using `fetchWithCache` (deduplicating concurrent calls).
 */
export async function fetchAddressesCached(
  tenantSlug: string,
  options?: { force?: boolean },
): Promise<AddressRead[]> {
  const key = buildAddressesCacheKey(tenantSlug);
  return fetchWithCache(
    key,
    () => Promise.resolve(AddressesService.listSavedAddresses(null, tenantSlug)),
    options,
  );
}

/**
 * Pre-warms saved addresses in the background without throwing on network errors.
 */
export function prefetchAddresses(tenantSlug: string): Promise<AddressRead[] | null> {
  if (!tenantSlug) return Promise.resolve(null);
  return fetchAddressesCached(tenantSlug).catch(() => null);
}

export interface UseAddressesResult {
  addresses: AddressRead[];
  loading: boolean;
  refresh: (options?: { force?: boolean }) => Promise<AddressRead[]>;
  setAddresses: Dispatch<SetStateAction<AddressRead[]>>;
}

/**
 * SWR hook for saved addresses (`/address-book`, Pickup Requests, Booking forms).
 *
 * Initializes synchronously from `query-cache.ts` so warm visits render in `< 16ms`
 * with `0` spinners, while revalidating in the background.
 */
export function useAddresses(tenantSlug: string): UseAddressesResult {
  const [addresses, setAddresses] = useState<AddressRead[]>(
    () => getCachedAddresses(tenantSlug) ?? [],
  );
  const [loading, setLoading] = useState<boolean>(
    () => !hasCachedAddresses(tenantSlug),
  );

  const refresh = useCallback(
    async (options?: { force?: boolean }): Promise<AddressRead[]> => {
      const force = options?.force ?? true;
      const hasWarm = hasCachedAddresses(tenantSlug);
      if (!hasWarm) {
        setLoading(true);
      }
      try {
        const result = await fetchAddressesCached(tenantSlug, { force });
        setAddresses(result);
        return result;
      } finally {
        setLoading(false);
      }
    },
    [tenantSlug],
  );

  useEffect(() => {
    let isCurrent = true;
    const warm = getCachedAddresses(tenantSlug);
    if (warm !== null) {
      setAddresses(warm);
      setLoading(false);
    } else {
      setLoading(true);
    }

    fetchAddressesCached(tenantSlug, { force: warm !== null })
      .then((fresh) => {
        if (isCurrent) {
          setAddresses(fresh);
        }
      })
      .catch((error: unknown) => {
        if (isCurrent) {
          console.error("Failed to fetch addresses", error);
        }
      })
      .finally(() => {
        if (isCurrent) {
          setLoading(false);
        }
      });

    return () => {
      isCurrent = false;
    };
  }, [tenantSlug]);

  return { addresses, loading, refresh, setAddresses };
}
