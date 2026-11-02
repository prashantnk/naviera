// frontend/src/components/dashboard/chart-model.test.ts
import type { DashboardDailyPoint } from "@/api_client";
import { describe, expect, it } from "vitest";

import { buildChartModel, niceAxisStep } from "./chart-model";

/** Builds a daily point for 2026-10-<day>. */
function point(day: number, in_transit: number, delivered: number, returned: number): DashboardDailyPoint {
  const dayLabel = String(day).padStart(2, "0");
  return { date: `2026-10-${dayLabel}`, in_transit, delivered, returned };
}

describe("niceAxisStep", () => {
  it("never goes below 1 for small integer counts", () => {
    expect(niceAxisStep(1)).toBe(1);
    expect(niceAxisStep(3)).toBe(1);
  });

  it("rounds to 1/2/5 x 10^n steps", () => {
    expect(niceAxisStep(7)).toBe(2);
    expect(niceAxisStep(18)).toBe(5);
    expect(niceAxisStep(300)).toBe(100);
  });
});

describe("buildChartModel", () => {
  it("flags an all-zero window as empty with no y ticks", () => {
    const model = buildChartModel([point(8, 0, 0, 0), point(9, 0, 0, 0)]);
    expect(model.isEmpty).toBe(true);
    expect(model.yTicks).toEqual([]);
    expect(model.bars).toHaveLength(2);
    expect(model.bars[0].segments.every((segment) => segment.heightPercent === 0)).toBe(true);
  });

  it("handles an empty series", () => {
    const model = buildChartModel([]);
    expect(model.isEmpty).toBe(true);
    expect(model.bars).toEqual([]);
  });

  it("scales stacked segments against a nice axis maximum", () => {
    const model = buildChartModel([point(8, 2, 1, 1), point(9, 1, 6, 1)]);
    expect(model.isEmpty).toBe(false);
    expect(model.axisMax).toBe(8);
    expect(model.yTicks.map((tick) => tick.value)).toEqual([0, 2, 4, 6, 8]);
    expect(model.yTicks[4].offsetPercent).toBe(100);

    const [first, second] = model.bars;
    expect(first.stackCount).toBe(4);
    expect(first.segments.map((segment) => segment.heightPercent)).toEqual([25, 12.5, 12.5]);
    expect(second.segments.map((segment) => segment.key)).toEqual(["in_transit", "delivered", "returned"]);
    expect(second.segments[1].heightPercent).toBe(75);
  });

  it("skips x-axis labels so at most 7 dates are shown", () => {
    const series = Array.from({ length: 30 }, (_, index) => point(index + 1, 1, 0, 0));
    const model = buildChartModel(series);
    const shownTicks = model.bars.filter((bar) => bar.showTick);
    expect(shownTicks.length).toBeLessThanOrEqual(7);
    expect(model.bars[0].showTick).toBe(true);
  });

  it("formats dates in UTC as short day-month labels", () => {
    const model = buildChartModel([point(8, 1, 0, 0)]);
    expect(model.bars[0].dateLabel).toMatch(/8\s+Oct/);
  });
});
