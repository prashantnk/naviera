// frontend/src/components/dashboard/dashboard-components.test.tsx
import type { DashboardDailyPoint, DashboardSummaryResponse } from "@/api_client";
import { ServiceFlow } from "@/api_client";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  formatCountMetric,
  formatDaysMetric,
  formatPercentMetric,
  MISSING_METRIC_HINT,
} from "./dashboard-model";
import { MetricTile } from "./metric-tile";
import { PerformanceSection } from "./performance-section";
import { StackedDailyBarChart } from "./stacked-bar-chart";

const SERIES: DashboardDailyPoint[] = [
  { date: "2026-10-08", in_transit: 2, delivered: 1, returned: 1 },
  { date: "2026-10-09", in_transit: 0, delivered: 3, returned: 0 },
];

/** Summary payload with every performance metric null except one. */
function summaryWithNullMetrics(): DashboardSummaryResponse {
  return {
    service_flow: ServiceFlow.B2C,
    days: 7,
    generated_at: "2026-10-16T00:00:00Z",
    stages: {
      to_be_shipped: 1,
      awaiting_pickup: 0,
      in_transit: 0,
      ndr_exceptions: 1,
      delivered: 13,
      rto: 1,
    },
    performance: {
      successful_delivery_rate: 92.9,
      first_attempt_delivery_rate: null,
      avg_days_to_first_attempt: null,
      on_time_delivery_rate: null,
    },
    daily_series: SERIES,
    appointments: null,
  };
}

describe("metric formatters", () => {
  it("render backend values verbatim and a dash for null", () => {
    expect(formatPercentMetric(83.3)).toBe("83.3%");
    expect(formatPercentMetric(null)).toBe("—");
    expect(formatDaysMetric(2)).toBe("2 days");
    expect(formatDaysMetric(1)).toBe("1 day");
    expect(formatDaysMetric(undefined)).toBe("—");
    expect(formatCountMetric(0)).toBe("0");
    expect(formatCountMetric(null)).toBe("—");
  });
});

describe("MetricTile", () => {
  it("shows the value when present", () => {
    render(<MetricTile label="Successful delivery rate" formattedValue="100%" />);
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
  });

  it("shows a dash with a 'Not enough data yet' tooltip for null metrics", () => {
    render(<MetricTile label="On-time delivery attempt" formattedValue={formatPercentMetric(null)} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    const tooltip = screen.getByRole("tooltip", { hidden: true });
    expect(tooltip).toHaveTextContent(MISSING_METRIC_HINT);
    const trigger = tooltip.parentElement as HTMLElement;
    expect(trigger).toHaveAttribute("tabindex", "0");
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
  });
});

describe("StackedDailyBarChart", () => {
  it("renders one bar per day with three stacked segments and a legend", () => {
    render(<StackedDailyBarChart series={SERIES} title="Daily shipment movement" />);
    expect(screen.getAllByTestId("chart-bar")).toHaveLength(2);
    expect(screen.getAllByTestId("chart-segment-delivered")).toHaveLength(2);
    const legend = screen.getByRole("figure", { name: "Daily shipment movement" });
    expect(within(legend).getAllByText("In Transit").length).toBeGreaterThan(0);
    expect(within(legend).getAllByText("Returned").length).toBeGreaterThan(0);
  });

  it("scales segment heights from the counts", () => {
    render(<StackedDailyBarChart series={SERIES} title="Chart" />);
    // Peak stack = 4 -> axis max 4; 2 in transit = 50%.
    const [firstInTransit] = screen.getAllByTestId("chart-segment-in_transit");
    expect(firstInTransit).toHaveStyle({ height: "50%" });
  });

  it("exposes the data in an accessible table", () => {
    render(<StackedDailyBarChart series={SERIES} title="Chart data" />);
    const table = screen.getByRole("table", { name: "Chart data" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
  });

  it("shows the empty message when nothing moved", () => {
    render(
      <StackedDailyBarChart
        series={[{ date: "2026-10-08", in_transit: 0, delivered: 0, returned: 0 }]}
        title="Empty chart"
        emptyMessage="Nothing moved"
      />
    );
    expect(screen.getByText("Nothing moved")).toBeInTheDocument();
    expect(screen.queryAllByTestId("chart-bar")).toHaveLength(0);
  });
});

describe("PerformanceSection", () => {
  it("renders null metrics as dashes and real ones verbatim", () => {
    render(
      <PerformanceSection
        days={7}
        onDaysChange={vi.fn()}
        summary={summaryWithNullMetrics()}
        isLoading={false}
        error={null}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByText("92.9%")).toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.getAllByRole("tooltip", { hidden: true })).toHaveLength(3);
  });

  it("requests a new window from the 7D / 14D / 30D toggle", () => {
    const onDaysChange = vi.fn();
    render(
      <PerformanceSection
        days={7}
        onDaysChange={onDaysChange}
        summary={summaryWithNullMetrics()}
        isLoading={false}
        error={null}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: "7D" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "30D" }));
    expect(onDaysChange).toHaveBeenCalledWith(30);
  });

  it("shows an error with a working retry button", () => {
    const onRetry = vi.fn();
    render(
      <PerformanceSection
        days={7}
        onDaysChange={vi.fn()}
        summary={null}
        isLoading={false}
        error="We couldn't load your dashboard data."
        onRetry={onRetry}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't load your dashboard data.");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
