// frontend/src/components/providers/wallet-provider.tsx
"use client";

import { WalletService, type WalletOverviewResponse } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
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
  const [wallet, setWallet] = useState<WalletOverviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [hasError, setHasError] = useState<boolean>(false);
  const inFlight = useRef<Promise<void> | null>(null);

  const refresh = useCallback(async () => {
    if (!tenantSlug) return;
    if (inFlight.current) return inFlight.current;
    const request = (async () => {
      try {
        const response = await WalletService.getWalletOverview(tenantSlug);
        setWallet(response);
        setHasError(false);
      } catch (error) {
        console.error("Failed to load wallet", error);
        setHasError(true);
      } finally {
        setIsLoading(false);
        inFlight.current = null;
      }
    })();
    inFlight.current = request;
    return request;
  }, [tenantSlug]);

  useEffect(() => {
    refresh();
    const handleUpdated = () => {
      refresh();
    };
    window.addEventListener(WALLET_UPDATED_EVENT, handleUpdated);
    return () => window.removeEventListener(WALLET_UPDATED_EVENT, handleUpdated);
  }, [refresh]);

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
