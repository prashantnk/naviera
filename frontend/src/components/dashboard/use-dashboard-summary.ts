// frontend/src/components/dashboard/use-dashboard-summary.ts
"use client";

import { DashboardService, type DashboardSummaryResponse } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { ServiceFlow } from "@/lib/workspace-flow";
import { useCallback, useEffect, useState } from "react";

import { API_SERVICE_FLOW, type DashboardWindowDays } from "./dashboard-model";

/** User-facing message when the summary request fails. */
const SUMMARY_ERROR_MESSAGE = "We couldn't load your dashboard data.";

export interface DashboardSummaryState {
  /** Latest successful response (kept while a new window is loading). */
  data: DashboardSummaryResponse | null;
  isLoading: boolean;
  error: string | null;
  /** Re-runs the request (used by the error state's Retry button). */
  retry: () => void;
}

/**
 * Fetches `GET /api/v1/dashboard/summary` for a flow and window.
 *
 * Spring analogy: a thin client-side `@Service` facade over the generated
 * OpenAPI client. Stale responses are cancelled when inputs change.
 *
 * @param flow - Flow whose stages/performance to load.
 * @param days - Window in days, or `null` to skip fetching (e.g. while the
 *   page is redirecting or another hook already covers this window).
 * @returns Data, loading / error flags and a retry callback.
 */
export function useDashboardSummary(
  flow: ServiceFlow,
  days: DashboardWindowDays | null
): DashboardSummaryState {
  const { tenantSlug } = useTenant();
  const [data, setData] = useState<DashboardSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(days !== null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<number>(0);

  useEffect(() => {
    if (days === null) return;
    let isCurrent = true;
    setIsLoading(true);
    setError(null);
    const request = DashboardService.getDashboardSummary(
      API_SERVICE_FLOW[flow],
      days,
      tenantSlug
    );
    request
      .then((response) => {
        if (isCurrent) setData(response);
      })
      .catch((requestError: unknown) => {
        if (!isCurrent) return;
        console.error("Failed to load dashboard summary", requestError);
        setError(SUMMARY_ERROR_MESSAGE);
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false);
      });
    return () => {
      isCurrent = false;
      request.cancel();
    };
  }, [flow, days, tenantSlug, attempt]);

  const retry = useCallback(() => setAttempt((previous) => previous + 1), []);

  return { data, isLoading, error, retry };
}
