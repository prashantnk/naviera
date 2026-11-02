// frontend/src/components/dashboard/performance-section.tsx
"use client";

import type { DashboardSummaryResponse } from "@/api_client";
import { cn } from "@/lib/utils";

import {
  DASHBOARD_WINDOW_OPTIONS,
  formatDaysMetric,
  formatPercentMetric,
  type DashboardWindowDays,
} from "./dashboard-model";
import { DashboardErrorState, DashboardSection, SkeletonBlock } from "./dashboard-section";
import { MetricTile } from "./metric-tile";
import { StackedDailyBarChart } from "./stacked-bar-chart";

/** Number of KPI tiles (drives the loading skeleton). */
const PERFORMANCE_TILE_COUNT = 4;

interface WindowToggleProps {
  value: DashboardWindowDays;
  onChange: (days: DashboardWindowDays) => void;
  disabled?: boolean;
}

/** 7D / 14D / 30D segmented toggle. */
export function WindowToggle({ value, onChange, disabled = false }: WindowToggleProps) {
  return (
    <div role="group" aria-label="Performance window" className="inline-flex rounded-lg border bg-muted/50 p-0.5">
      {DASHBOARD_WINDOW_OPTIONS.map((option) => {
        const isSelected = option === value;
        return (
          <button
            key={option}
            type="button"
            aria-pressed={isSelected}
            disabled={disabled}
            onClick={() => onChange(option)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait",
              isSelected
                ? "bg-card text-primary shadow-xs"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {option}D
          </button>
        );
      })}
    </div>
  );
}

interface PerformanceSectionProps {
  days: DashboardWindowDays;
  onDaysChange: (days: DashboardWindowDays) => void;
  summary: DashboardSummaryResponse | null;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

/**
 * "Performance" block: 4 KPI tiles + stacked daily chart for the selected
 * window. Every value is rendered as received from the backend.
 */
export function PerformanceSection({
  days,
  onDaysChange,
  summary,
  isLoading,
  error,
  onRetry,
}: PerformanceSectionProps) {
  const performance = summary?.performance;
  const isInitialLoad = isLoading && !summary;
  const isRefreshing = isLoading && Boolean(summary);

  return (
    <DashboardSection
      headingId="dashboard-performance-heading"
      title="Performance"
      description={`Shipments created in the last ${days} days`}
      actions={<WindowToggle value={days} onChange={onDaysChange} disabled={isLoading} />}
    >
      {error && !isLoading ? (
        <DashboardErrorState message={error} onRetry={onRetry} />
      ) : isInitialLoad || !performance || !summary ? (
        <div aria-label="Loading performance" className="space-y-4">
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            {Array.from({ length: PERFORMANCE_TILE_COUNT }, (_, index) => (
              <SkeletonBlock key={index} className="h-16" />
            ))}
          </div>
          <SkeletonBlock className="h-56" />
        </div>
      ) : (
        <div className="space-y-5">
          <div
            aria-busy={isRefreshing}
            className={cn(
              "grid grid-cols-2 gap-2 transition-opacity lg:grid-cols-4",
              isRefreshing && "opacity-60"
            )}
          >
            <MetricTile
              label="On-time delivery attempt"
              formattedValue={formatPercentMetric(performance.on_time_delivery_rate)}
            />
            <MetricTile
              label="Avg time for first attempt"
              formattedValue={formatDaysMetric(performance.avg_days_to_first_attempt)}
            />
            <MetricTile
              label="Successful delivery rate"
              formattedValue={formatPercentMetric(performance.successful_delivery_rate)}
            />
            <MetricTile
              label="First attempt delivery"
              formattedValue={formatPercentMetric(performance.first_attempt_delivery_rate)}
            />
          </div>
          <StackedDailyBarChart
            series={summary.daily_series}
            title={`Daily shipment movement, last ${days} days`}
            isRefreshing={isRefreshing}
            emptyMessage={`No shipment moved in the last ${days} days.`}
          />
        </div>
      )}
    </DashboardSection>
  );
}
