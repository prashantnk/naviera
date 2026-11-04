// frontend/src/components/providers/wallet-provider.tsx
"use client";

import {
  DashboardService,
  ServiceFlow,
  ShipmentsService,
  WalletService,
  type WalletOverviewResponse,
} from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import {
  buildQueryCacheKey,
  getCachedQuery,
  hasCachedQuery,
  invalidateQueryCache,
  setCachedQuery,
} from "@/lib/query-cache";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

/** Window event fired by every flow that changes the wallet (recharge, booking, refund, approval). */
export const WALLET_UPDATED_EVENT = "wallet-updated";

/** Shared wallet state exposed to the header pill, dashboard card and wallet page. */
export interface WalletContextValue {
  /** Latest `GET /api/v1/wallet` payload, or null before the first load / on error. */
  wallet: WalletOverviewResponse | null;
  /** True until the first fetch settles. */
  isLoading: boolean;
  /** True when the most recent fetch failed. */
  hasError: boolean;
  /** Re-fetches the overview (deduplicated while a request is in flight). */
  refresh: () => Promise<void>;
}

const WalletContext = createContext<WalletContextValue | undefined>(undefined);

/**
 * Single source of the merchant's wallet overview for the whole app shell.
 *
 * Before this provider, the header pill and the dashboard wallet card each called
 * `GET /api/v1/wallet` (about 11 s per call against the remote DB in dev). Now one
 * request serves every consumer, and any `wallet-updated` event refreshes it once.
 * Mounted inside `AuthGuard` in `(app)/layout.tsx`, so the user is authenticated.
 */
export function WalletProvider({ children }: { children: React.ReactNode }) {
  const { tenantSlug } = useTenant();
  const cacheKey = buildQueryCacheKey(tenantSlug, "session", "wallet-overview");
  const [wallet, setWallet] = useState<WalletOverviewResponse | null>(() =>
    getCachedQuery<WalletOverviewResponse>(cacheKey)
  );
  const [isLoading, setIsLoading] = useState<boolean>(
    () => !hasCachedQuery(cacheKey)
  );
  const [hasError, setHasError] = useState<boolean>(false);
  const inFlight = useRef<Promise<void> | null>(null);

  const refresh = useCallback(async () => {
    if (!tenantSlug) return;
    if (inFlight.current) return inFlight.current;
    const cached = getCachedQuery<WalletOverviewResponse>(cacheKey);
    if (cached !== null) {
      setWallet(cached);
    }
    const request = (async () => {
      try {
        const response = await WalletService.getWalletOverview(tenantSlug);
        setCachedQuery(cacheKey, response);
        setWallet(response);
        setHasError(false);
      } catch (error) {
        console.error("Failed to load wallet", error);
        if (cached === null) {
          setHasError(true);
        }
      } finally {
        setIsLoading(false);
        inFlight.current = null;
      }
    })();
    inFlight.current = request;
    return request;
  }, [tenantSlug, cacheKey]);

  useEffect(() => {
    refresh();
    const handleUpdated = () => {
      invalidateQueryCache(tenantSlug);
      refresh();
    };
    window.addEventListener(WALLET_UPDATED_EVENT, handleUpdated);
    return () => window.removeEventListener(WALLET_UPDATED_EVENT, handleUpdated);
  }, [refresh, tenantSlug]);

  // Background cache warming for primary Dashboard & Orders screens so the
  // very first click between Dashboard <-> Orders renders in 0ms without a spinner.
  useEffect(() => {
    if (!tenantSlug || typeof window === "undefined" || Boolean(process.env?.VITEST)) {
      return;
    }
    const timer = window.setTimeout(() => {
      const summary30Key = buildQueryCacheKey(tenantSlug, "session", "dashboard-summary", {
        flow: ServiceFlow.B2C,
        days: 30,
      });
      if (!hasCachedQuery(summary30Key)) {
        DashboardService.getDashboardSummary(ServiceFlow.B2C, 30, tenantSlug)
          .then((res) => setCachedQuery(summary30Key, res))
          .catch(() => undefined);
      }
      const shipmentsKey = buildQueryCacheKey(tenantSlug, "session", "shipments-list", {
        isB2B: false,
        page: 1,
        size: 50,
        direction: "ALL",
      });
      if (!hasCachedQuery(shipmentsKey)) {
        ShipmentsService.listShipments(1, 50, false, undefined, undefined)
          .then((res) =>
            setCachedQuery(shipmentsKey, {
              items: res.items ?? [],
              total: res.total ?? 0,
            })
          )
          .catch(() => undefined);
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, [tenantSlug]);

  const value = useMemo<WalletContextValue>(
    () => ({ wallet, isLoading, hasError, refresh }),
    [wallet, isLoading, hasError, refresh],
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
}

/**
 * Reads the shared wallet state.
 *
 * @returns The wallet context.
 * @throws If called outside `WalletProvider`.
 */
export function useWallet(): WalletContextValue {
  const context = useContext(WalletContext);
  if (context === undefined) {
    throw new Error("useWallet must be used within a WalletProvider");
  }
  return context;
}
