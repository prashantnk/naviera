// frontend/src/app/[tenant_slug]/(app)/dashboard/page.tsx
"use client";

import type { B2CStageSummary } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { B2COrderSummary } from "@/components/dashboard/b2c-order-summary";
import { DashboardRightRail } from "@/components/dashboard/dashboard-right-rail";
import {
  isB2CStages,
  STAGE_SUMMARY_WINDOW_DAYS,
  type DashboardWindowDays,
} from "@/components/dashboard/dashboard-model";
import { PerformanceSection } from "@/components/dashboard/performance-section";
import { useDashboardSummary } from "@/components/dashboard/use-dashboard-summary";
import { useTenant } from "@/components/providers/tenant-provider";
import { ServiceFlow } from "@/lib/workspace-flow";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/** Default Performance window, matching Delhivery's initial 7D selection. */
const DEFAULT_PERFORMANCE_DAYS: DashboardWindowDays = 7;

/**
 * B2C Express home dashboard (Delhivery One "Domestic" home parity):
 * Order summary (30 days) + Performance (7/14/30 days) + right rail.
 * B2B-only users are redirected to the B2B dashboard.
 */
export default function B2CDashboardPage() {
  const { routeTo, tenant } = useTenant();
  const { canAccessB2C, canAccessB2B } = useUser();
  const router = useRouter();
  const shouldRedirectToB2B = !canAccessB2C && canAccessB2B;

  const [performanceDays, setPerformanceDays] =
    useState<DashboardWindowDays>(DEFAULT_PERFORMANCE_DAYS);

  const stageSummary = useDashboardSummary(
    ServiceFlow.B2C,
    shouldRedirectToB2B ? null : STAGE_SUMMARY_WINDOW_DAYS
  );
  // The 30-day window is already loaded for the stage cards; reuse it.
  const reusesStageWindow = performanceDays === STAGE_SUMMARY_WINDOW_DAYS;
  const windowSummary = useDashboardSummary(
    ServiceFlow.B2C,
    shouldRedirectToB2B || reusesStageWindow ? null : performanceDays
  );
  const performanceSummary = reusesStageWindow ? stageSummary : windowSummary;

  useEffect(() => {
    if (shouldRedirectToB2B) router.replace(routeTo("/b2b/dashboard"));
  }, [shouldRedirectToB2B, router, routeTo]);

  if (shouldRedirectToB2B) return null;

  const stages: B2CStageSummary | null =
    stageSummary.data && isB2CStages(stageSummary.data.stages) ? stageSummary.data.stages : null;

  return (
    <div className="mx-auto max-w-7xl space-y-5 pb-12">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Home</h1>
        <p className="text-sm text-muted-foreground">
          B2C Express Parcel overview{tenant?.name ? ` for ${tenant.name}` : ""}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-5">
          <B2COrderSummary
            stages={stages}
            isLoading={stageSummary.isLoading}
            error={stageSummary.error}
            onRetry={stageSummary.retry}
          />
          <PerformanceSection
            days={performanceDays}
            onDaysChange={setPerformanceDays}
            summary={performanceSummary.data}
            isLoading={performanceSummary.isLoading}
            error={performanceSummary.error}
            onRetry={performanceSummary.retry}
          />
        </div>
        <DashboardRightRail flow={ServiceFlow.B2C} />
      </div>
    </div>
  );
}
