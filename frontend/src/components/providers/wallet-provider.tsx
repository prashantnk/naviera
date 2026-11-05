// frontend/src/components/providers/wallet-provider.tsx
"use client";

import {
  AppointmentsService,
  AppointmentTab,
  DashboardService,
  DisputesService,
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
import { useUser } from "@/components/auth/auth-guard";
import type { UserCapabilities } from "@/components/auth/capabilities";
import { CATEGORY_ORDER_BY_FLOW } from "@/components/exceptions/exception-meta";
import { useTenant } from "@/components/providers/tenant-provider";
import { useWorkspaceFlow } from "@/components/providers/workspace-flow-provider";
import { fetchAddressesCached } from "@/hooks/use-addresses";
import {
  buildQueryCacheKey,
  fetchWithCache,
  getCachedQuery,
  hasCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

/** Window event fired by every flow that changes the wallet (recharge, booking, refund, approval). */
export const WALLET_UPDATED_EVENT = "wallet-updated";

/**
 * Delay before background pre-warming starts, so the screen the user opened
 * gets the (single, free-tier) backend to itself for its own first requests.
 */
export const PREWARM_START_DELAY_MS = 1_500;

/** Longest we wait for the browser to go idle before pre-warming anyway. */
const PREWARM_IDLE_TIMEOUT_MS = 2_000;

/** Pre-warm requests allowed in flight at once. */
export const PREWARM_CONCURRENCY = 2;

/** One background warm-up step; resolves when its cache entry is filled or skipped. */
export type PrewarmJob = () => Promise<unknown>;

/** Capabilities that decide which screens are worth pre-warming. */
export type PrewarmCapabilities = Pick<
  UserCapabilities,
  "isStaff" | "canBook" | "canViewFinanceDocuments"
>;

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
 * Returns a job that fills `key` via `load` unless the screen already cached it
 * by the time the job runs.
 *
 * @param key - Cache key the target screen reads.
 * @param load - Request producing exactly the payload that screen caches.
 * @returns The pre-warm job.
 */
function _warm(key: string, load: () => Promise<unknown>): PrewarmJob {
  return async () => {
    if (hasCachedQuery(key)) return;
    await fetchWithCache(key, load);
  };
}

/**
 * Lists the background warm-ups for the screens this user can open in the
 * active flow, most-visited first. Screens the role cannot open, and the other
 * flow, are skipped so the user's free backend instance is not loaded with
 * requests that would only be refused or never read.
 *
 * @param tenantSlug - Active tenant.
 * @param flow - Active workspace flow.
 * @param capabilities - The user's capability map.
 * @returns Ordered jobs.
 */
export function buildPrewarmJobs(
  tenantSlug: string,
  flow: ServiceFlow,
  capabilities: PrewarmCapabilities,
): PrewarmJob[] {
  const isB2B = flow === ServiceFlow.B2B;
  const viewScope = capabilities.isStaff ? "staff" : "customer";
  const key = (scope: string, endpoint: string, params?: Record<string, unknown>) =>
    buildQueryCacheKey(tenantSlug, scope, endpoint, params);

  const jobs: PrewarmJob[] = [
    _warm(key("session", "dashboard-summary", { flow, days: 30 }), () =>
      DashboardService.getDashboardSummary(flow, 30, tenantSlug),
    ),
    _warm(key("session", "shipments-list", { isB2B, page: 1, size: 50, direction: "ALL" }), () =>
      ShipmentsService.listShipments(1, 50, isB2B, undefined, undefined).then((res) => ({
        items: res.items ?? [],
        total: res.total ?? 0,
      })),
    ),
    _warm(key("session", "manifests-list", { serviceFlow: flow, status: "ALL" }), () =>
      ManifestsService.listManifests(flow, null, null, tenantSlug).then((rows) => rows || []),
    ),
  ];

  if (capabilities.canBook) {
    // Create Pickup Request opens on the first saved warehouse.
    jobs.push(async () => {
      const addresses = await fetchAddressesCached(tenantSlug);
      const firstWarehouse = addresses[0];
      if (!firstWarehouse) return;
      await _warm(
        key("session", "eligible-shipments", { serviceFlow: flow, locationId: firstWarehouse.id }),
        () =>
          ManifestsService.listEligibleShipments(flow, firstWarehouse.id, tenantSlug).then(
            (rows) => rows || [],
          ),
      )();
    });
  }

  const primaryExceptionCategory = CATEGORY_ORDER_BY_FLOW[flow][0];
  jobs.push(
    _warm(
      key("session", "exceptions-workspace", {
        serviceFlow: flow,
        category: primaryExceptionCategory,
        actionable: false,
        search: "",
        page: 1,
      }),
      async () => {
        const [summary, list] = await Promise.all([
          ExceptionsService.getExceptionsSummary(flow, tenantSlug),
          ExceptionsService.listExceptions(
            flow,
            primaryExceptionCategory,
            false,
            null,
            1,
            20,
            tenantSlug,
          ),
        ]);
        return { summary, list };
      },
    ),
  );

  if (capabilities.canViewFinanceDocuments) {
    jobs.push(
      _warm(key(viewScope, "invoices", { tab: "INVOICE", search: "" }), () =>
        InvoicesService.listBillingInvoices("INVOICE", null, tenantSlug).then((rows) => rows || []),
      ),
      _warm(key(viewScope, "remittances", { search: "", date: "" }), () =>
        RemittancesService.listRemittances(null, null, tenantSlug).then((rows) => rows || []),
      ),
    );
  }

  jobs.push(
    _warm(key(viewScope, "weight-mismatch", { search: "" }), () =>
      DisputesService.listWeightMismatchDisputes(null, null, tenantSlug).then((rows) => rows || []),
    ),
    _warm(key(viewScope, "support-tickets", { tab: "OPEN", search: "" }), () =>
      SupportTicketsService.listSupportTickets("OPEN", null).then((rows) => rows || []),
    ),
  );

  if (isB2B) {
    jobs.push(
      _warm(
        key("session", "b2b-appointments", {
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
        }),
        () =>
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
            tenantSlug,
          ),
      ),
    );
  }
  return jobs;
}

/**
 * Runs jobs with at most `concurrency` in flight, in order, stopping early
 * once `isCancelled()` turns true. Job failures are swallowed: a pre-warm miss
 * only means the screen loads normally.
 *
 * @param jobs - Ordered jobs.
 * @param concurrency - Max jobs in flight.
 * @param isCancelled - Checked before each job starts.
 */
export async function runPrewarmJobs(
  jobs: readonly PrewarmJob[],
  concurrency: number,
  isCancelled: () => boolean,
): Promise<void> {
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < jobs.length && !isCancelled()) {
      const job = jobs[next];
      next += 1;
      await job().catch(() => undefined);
    }
  };
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, worker));
}

/**
 * Single source of the merchant's wallet overview for the whole app shell.
 *
 * Before this provider, the header pill and the dashboard wallet card each called
 * `GET /api/v1/wallet` (about 11 s per call against the remote DB in dev). Now one
 * request serves every consumer, and any `wallet-updated` event refreshes it once.
 * Mounted inside `AuthGuard` in `(app)/layout.tsx`, so the user is authenticated.
 *
 * It also pre-warms the query cache for the user's other screens, but only
 * after the opened screen had the backend to itself, two requests at a time.
 */
export function WalletProvider({ children }: { children: React.ReactNode }) {
  const { tenantSlug } = useTenant();
  const {
    capabilities: { isStaff, canBook, canViewFinanceDocuments },
  } = useUser();
  const { activeFlow } = useWorkspaceFlow();
  const cacheKey = buildQueryCacheKey(tenantSlug, "session", "wallet-overview");
  const [wallet, setWallet] = useState<WalletOverviewResponse | null>(() =>
    getCachedQuery<WalletOverviewResponse>(cacheKey)
  );
  const [isLoading, setIsLoading] = useState<boolean>(
    () => !hasCachedQuery(cacheKey)
  );
  const [hasError, setHasError] = useState<boolean>(false);
  const inFlight = useRef<Promise<void> | null>(null);
  const latestRequestId = useRef(0);

  /**
   * Loads the overview. `force` starts a new request even while one is in
   * flight (after a wallet change the older response is already stale); only
   * the most recent request may update state.
   */
  const load = useCallback(
    async (force: boolean): Promise<void> => {
      if (!tenantSlug) return;
      if (inFlight.current && !force) return inFlight.current;
      const cached = getCachedQuery<WalletOverviewResponse>(cacheKey);
      if (cached !== null) {
        setWallet(cached);
      }
      const requestId = ++latestRequestId.current;
      const request = (async () => {
        try {
          const response = await WalletService.getWalletOverview(tenantSlug);
          if (requestId !== latestRequestId.current) return;
          setCachedQuery(cacheKey, response);
          setWallet(response);
          setHasError(false);
        } catch (error) {
          if (requestId !== latestRequestId.current) return;
          console.error("Failed to load wallet", error);
          if (cached === null) {
            setHasError(true);
          }
        } finally {
          if (requestId === latestRequestId.current) {
            setIsLoading(false);
            inFlight.current = null;
          }
        }
      })();
      inFlight.current = request;
      return request;
    },
    [tenantSlug, cacheKey],
  );

  const refresh = useCallback(() => load(false), [load]);

  useEffect(() => {
    void load(false);
    // `query-cache.ts` already evicted every cached response for this event.
    const handleUpdated = () => {
      void load(true);
    };
    window.addEventListener(WALLET_UPDATED_EVENT, handleUpdated);
    return () => window.removeEventListener(WALLET_UPDATED_EVENT, handleUpdated);
  }, [load]);

  useEffect(() => {
    if (!tenantSlug || typeof window === "undefined" || Boolean(process.env?.VITEST)) {
      return;
    }
    let cancelled = false;
    let idleHandle: number | null = null;
    const start = () => {
      idleHandle = null;
      void runPrewarmJobs(
        buildPrewarmJobs(tenantSlug, activeFlow, { isStaff, canBook, canViewFinanceDocuments }),
        PREWARM_CONCURRENCY,
        () => cancelled,
      );
    };
    const delayTimer = window.setTimeout(() => {
      if (typeof window.requestIdleCallback === "function") {
        idleHandle = window.requestIdleCallback(start, { timeout: PREWARM_IDLE_TIMEOUT_MS });
      } else {
        start();
      }
    }, PREWARM_START_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(delayTimer);
      if (idleHandle !== null && typeof window.cancelIdleCallback === "function") {
        window.cancelIdleCallback(idleHandle);
      }
    };
  }, [tenantSlug, activeFlow, isStaff, canBook, canViewFinanceDocuments]);

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
