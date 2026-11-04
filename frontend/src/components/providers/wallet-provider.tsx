// frontend/src/components/providers/wallet-provider.tsx
"use client";

import {
  AppointmentsService,
  AppointmentTab,
  DashboardService,
  DisputesService,
  ExceptionCategory,
  ExceptionsService,
  InvoicesService,
  ManifestsService,
  RemittancesService,
  ServiceFlow,
  ShipmentsService,
  SupportTicketsService,
  WalletService,
  type WalletOverviewResponse,
} from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { fetchAddressesCached } from "@/hooks/use-addresses";
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

  // Two-stage staggered background cache pre-warming so navigating to any
  // B2C or B2B workspace screen (Dashboard, Orders, Pickup Requests, Create
  // Pickup Request, Saved Addresses, Exceptions, Invoices, Remittances,
  // Weight Mismatch, Support, Appointments) renders in < 50ms with 0 spinners.
  useEffect(() => {
    if (!tenantSlug || typeof window === "undefined" || Boolean(process.env?.VITEST)) {
      return;
    }

    // Stage 1 (immediate +50ms): Dashboard, Orders/LRs, Pickup Requests (Manifests),
    // and Saved Addresses + Eligible Shipments for Create Pickup Request.
    const stage1Timer = window.setTimeout(() => {
      for (const flow of [ServiceFlow.B2C, ServiceFlow.B2B]) {
        const summary30Key = buildQueryCacheKey(tenantSlug, "session", "dashboard-summary", {
          flow,
          days: 30,
        });
        if (!hasCachedQuery(summary30Key)) {
          DashboardService.getDashboardSummary(flow, 30, tenantSlug)
            .then((res) => setCachedQuery(summary30Key, res))
            .catch(() => undefined);
        }

        const manifestsKey = buildQueryCacheKey(tenantSlug, "session", "manifests-list", {
          serviceFlow: flow,
          status: "ALL",
        });
        if (!hasCachedQuery(manifestsKey)) {
          ManifestsService.listManifests(flow, null, null, tenantSlug)
            .then((rows) => setCachedQuery(manifestsKey, rows || []))
            .catch(() => undefined);
        }
      }

      for (const isB2B of [false, true]) {
        const shipmentsKey = buildQueryCacheKey(tenantSlug, "session", "shipments-list", {
          isB2B,
          page: 1,
          size: 50,
          direction: "ALL",
        });
        if (!hasCachedQuery(shipmentsKey)) {
          ShipmentsService.listShipments(1, 50, isB2B, undefined, undefined)
            .then((res) =>
              setCachedQuery(shipmentsKey, {
                items: res.items ?? [],
                total: res.total ?? 0,
              })
            )
            .catch(() => undefined);
        }
      }

      fetchAddressesCached(tenantSlug)
        .then((addrs) => {
          const firstWarehouse = addrs[0];
          if (!firstWarehouse) return;
          for (const flow of [ServiceFlow.B2C, ServiceFlow.B2B]) {
            const eligibleKey = buildQueryCacheKey(
              tenantSlug,
              "session",
              "eligible-shipments",
              { serviceFlow: flow, locationId: firstWarehouse.id }
            );
            if (!hasCachedQuery(eligibleKey)) {
              ManifestsService.listEligibleShipments(
                flow,
                firstWarehouse.id,
                tenantSlug
              )
                .then((rows) => setCachedQuery(eligibleKey, rows || []))
                .catch(() => undefined);
            }
          }
        })
        .catch(() => undefined);
    }, 50);

    // Stage 2 (+350ms idle): Exceptions, Invoices, Remittances, Weight Mismatch,
    // Support Tickets, and B2B Appointments.
    const stage2Timer = window.setTimeout(() => {
      const b2cExceptionsKey = buildQueryCacheKey(
        tenantSlug,
        "session",
        "exceptions-workspace",
        {
          serviceFlow: ServiceFlow.B2C,
          category: ExceptionCategory.SHIPMENT_EXCEPTIONS,
          actionable: false,
          search: "",
          page: 1,
        }
      );
      if (!hasCachedQuery(b2cExceptionsKey)) {
        Promise.all([
          ExceptionsService.getExceptionsSummary(ServiceFlow.B2C, tenantSlug),
          ExceptionsService.listExceptions(
            ServiceFlow.B2C,
            ExceptionCategory.SHIPMENT_EXCEPTIONS,
            false,
            null,
            1,
            20,
            tenantSlug
          ),
        ])
          .then(([summary, list]) =>
            setCachedQuery(b2cExceptionsKey, { summary, list })
          )
          .catch(() => undefined);
      }

      const invoicesStaffKey = buildQueryCacheKey(tenantSlug, "staff", "invoices", {
        tab: "INVOICE",
        search: "",
      });
      const invoicesCustKey = buildQueryCacheKey(tenantSlug, "customer", "invoices", {
        tab: "INVOICE",
        search: "",
      });
      if (!hasCachedQuery(invoicesStaffKey) && !hasCachedQuery(invoicesCustKey)) {
        InvoicesService.listBillingInvoices("INVOICE", null, tenantSlug)
          .then((rows) => {
            const list = rows || [];
            setCachedQuery(invoicesStaffKey, list);
            setCachedQuery(invoicesCustKey, list);
          })
          .catch(() => undefined);
      }

      const remitStaffKey = buildQueryCacheKey(tenantSlug, "staff", "remittances", {
        search: "",
        date: "",
      });
      const remitCustKey = buildQueryCacheKey(tenantSlug, "customer", "remittances", {
        search: "",
        date: "",
      });
      if (!hasCachedQuery(remitStaffKey) && !hasCachedQuery(remitCustKey)) {
        RemittancesService.listRemittances(null, null, tenantSlug)
          .then((rows) => {
            const list = rows || [];
            setCachedQuery(remitStaffKey, list);
            setCachedQuery(remitCustKey, list);
          })
          .catch(() => undefined);
      }

      const mismatchStaffKey = buildQueryCacheKey(tenantSlug, "staff", "weight-mismatch", {
        search: "",
      });
      const mismatchCustKey = buildQueryCacheKey(tenantSlug, "customer", "weight-mismatch", {
        search: "",
      });
      if (!hasCachedQuery(mismatchStaffKey) && !hasCachedQuery(mismatchCustKey)) {
        DisputesService.listWeightMismatchDisputes(null, null, tenantSlug)
          .then((rows) => {
            const list = rows || [];
            setCachedQuery(mismatchStaffKey, list);
            setCachedQuery(mismatchCustKey, list);
          })
          .catch(() => undefined);
      }

      const supportStaffKey = buildQueryCacheKey("workspace", "staff", "support-tickets", {
        tab: "OPEN",
        search: "",
      });
      const supportCustKey = buildQueryCacheKey("workspace", "customer", "support-tickets", {
        tab: "OPEN",
        search: "",
      });
      if (!hasCachedQuery(supportStaffKey) && !hasCachedQuery(supportCustKey)) {
        SupportTicketsService.listSupportTickets("OPEN", null)
          .then((rows) => {
            const list = rows || [];
            setCachedQuery(supportStaffKey, list);
            setCachedQuery(supportCustKey, list);
          })
          .catch(() => undefined);
      }

      const appointmentsKey = buildQueryCacheKey(tenantSlug, "session", "b2b-appointments", {
        tab: AppointmentTab.PENDING,
        search: "",
        consignee: "",
        city: "",
        status: "ALL",
        pddFrom: "",
        pddTo: "",
        expiredOnly: false,
        page: 1,
        size: 10,
      });
      if (!hasCachedQuery(appointmentsKey)) {
        AppointmentsService.listAppointments(
          AppointmentTab.PENDING,
          null,
          null,
          null,
          null,
          null,
          null,
          false,
          1,
          10,
          tenantSlug
        )
          .then((res) => setCachedQuery(appointmentsKey, res))
          .catch(() => undefined);
      }
    }, 350);

    return () => {
      window.clearTimeout(stage1Timer);
      window.clearTimeout(stage2Timer);
    };
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
