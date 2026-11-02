// frontend/src/components/dashboard/dashboard-model.ts
/**
 * Pure (React-free) helpers shared by the B2C and B2B home dashboards.
 *
 * Everything here is presentation-only: values are formatted exactly as the
 * backend `/api/v1/dashboard/summary` returns them. No business metric is
 * derived in the browser (Zero Frontend Math directive).
 *
 * Spring analogy: a stateless `@Component` formatter used by the view layer.
 */

import type {
  B2BStageSummary,
  B2CStageSummary,
  WalletOverviewResponse,
} from "@/api_client";
import { ServiceFlow as ApiServiceFlow } from "@/api_client";
import { ServiceFlow } from "@/lib/workspace-flow";

/** Window (in days) the backend accepts for the summary endpoint. */
export type DashboardWindowDays = 7 | 14 | 30;

/** Performance toggle options, in display order (7D / 14D / 30D). */
export const DASHBOARD_WINDOW_OPTIONS: readonly DashboardWindowDays[] = [7, 14, 30];

/** Stage counters ("Order summary" / "Shipment summary") always use 30 days. */
export const STAGE_SUMMARY_WINDOW_DAYS: DashboardWindowDays = 30;

/** Placeholder rendered when the backend returns `null` for a metric. */
export const MISSING_METRIC_PLACEHOLDER = "—";

/** Tooltip explaining why a metric shows the placeholder. */
export const MISSING_METRIC_HINT = "Not enough data yet";

/** Locale used for every number / date on the dashboards. */
const DASHBOARD_LOCALE = "en-IN";

/** Fallback ISO currency when the wallet payload omits one. */
const DEFAULT_CURRENCY = "INR";

/** Maps the UI flow enum to the generated API client enum. */
export const API_SERVICE_FLOW: Record<ServiceFlow, ApiServiceFlow> = {
  [ServiceFlow.B2C]: ApiServiceFlow.B2C,
  [ServiceFlow.B2B]: ApiServiceFlow.B2B,
};

/** `wallet_config` key holding the minimum balance for each flow. */
const MIN_BALANCE_CONFIG_KEY: Record<ServiceFlow, string> = {
  [ServiceFlow.B2C]: "min_wallet_balance_b2c",
  [ServiceFlow.B2B]: "min_wallet_balance_b2b",
};

/**
 * Narrows the summary `stages` union to the B2C (Domestic) shape.
 *
 * @param stages - `stages` object from the summary response.
 * @returns True when the payload carries the B2C stage keys.
 */
export function isB2CStages(
  stages: B2CStageSummary | B2BStageSummary
): stages is B2CStageSummary {
  return "to_be_shipped" in stages;
}

/**
 * Narrows the summary `stages` union to the B2B (Surface) shape.
 *
 * @param stages - `stages` object from the summary response.
 * @returns True when the payload carries the B2B stage keys.
 */
export function isB2BStages(
  stages: B2CStageSummary | B2BStageSummary
): stages is B2BStageSummary {
  return "lrs_manifested" in stages;
}

/**
 * Reports whether every stage counter in the window is zero (empty state).
 *
 * @param stages - Stage counters from the backend.
 * @returns True when there is no shipment in any stage.
 */
export function hasNoStageActivity(
  stages: B2CStageSummary | B2BStageSummary
): boolean {
  return Object.values(stages).every((count) => count === 0);
}

/**
 * Formats a plain number with Indian digit grouping and at most 1 decimal.
 *
 * @param value - Number exactly as returned by the backend.
 * @returns Localised string, e.g. `1,234.5`.
 */
function _formatNumber(value: number): string {
  return value.toLocaleString(DASHBOARD_LOCALE, { maximumFractionDigits: 1 });
}

/**
 * Formats a backend percentage (already 0-100, rounded server-side).
 *
 * @param value - Percentage or `null` when not derivable.
 * @returns e.g. `83.3%`, or the placeholder for `null` / `undefined`.
 */
export function formatPercentMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING_METRIC_PLACEHOLDER;
  return `${_formatNumber(value)}%`;
}

/**
 * Formats a backend day count (e.g. average days to first attempt).
 *
 * @param value - Days or `null` when not derivable.
 * @returns e.g. `2 days` / `1 day`, or the placeholder.
 */
export function formatDaysMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING_METRIC_PLACEHOLDER;
  const unit = value === 1 ? "day" : "days";
  return `${_formatNumber(value)} ${unit}`;
}

/**
 * Formats an optional integer counter (e.g. appointments).
 *
 * @param value - Count or `null` when not derivable.
 * @returns Localised count, or the placeholder.
 */
export function formatCountMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING_METRIC_PLACEHOLDER;
  return value.toLocaleString(DASHBOARD_LOCALE);
}

/**
 * Formats a wallet money value as currency (display only, no arithmetic).
 *
 * @param value - Money value from the wallet API.
 * @param currency - ISO 4217 currency from the wallet API.
 * @returns e.g. `₹1,96,431.00` or `-₹3,880.29`.
 */
export function formatWalletMoney(value: number, currency?: string): string {
  return new Intl.NumberFormat(DASHBOARD_LOCALE, {
    style: "currency",
    currency: currency || DEFAULT_CURRENCY,
    minimumFractionDigits: 2,
  }).format(value);
}

/**
 * Reads the tenant's configured minimum wallet balance for a flow.
 *
 * @param wallet - Wallet overview from `GET /api/v1/wallet`.
 * @param flow - Flow whose threshold applies.
 * @returns The configured threshold, or `null` if the backend sent none.
 */
export function getMinimumWalletBalance(
  wallet: WalletOverviewResponse,
  flow: ServiceFlow
): number | null {
  const configured = wallet.wallet_config?.[MIN_BALANCE_CONFIG_KEY[flow]];
  return typeof configured === "number" ? configured : null;
}

/**
 * Formats an ISO `YYYY-MM-DD` (UTC) day as a short axis label, e.g. `8 Oct`.
 *
 * @param isoDate - Day string from `daily_series[].date`.
 * @returns Short day + month label, independent of the viewer's timezone.
 */
export function formatDayLabel(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString(DASHBOARD_LOCALE, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
