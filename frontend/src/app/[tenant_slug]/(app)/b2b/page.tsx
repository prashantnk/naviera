// frontend/src/app/[tenant_slug]/(app)/b2b/page.tsx
"use client";

import type { B2BStageSummary } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { AppointmentManagement, B2BShipmentSummary } from "@/components/dashboard/b2b-shipment-summary";
import { DashboardRightRail } from "@/components/dashboard/dashboard-right-rail";
import { isB2BStages, STAGE_SUMMARY_WINDOW_DAYS } from "@/components/dashboard/dashboard-model";
import { useDashboardSummary } from "@/components/dashboard/use-dashboard-summary";
import { useTenant } from "@/components/providers/tenant-provider";
import { ServiceFlow } from "@/lib/workspace-flow";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * B2B Cargo home dashboard (Delhivery One "B2B Surface" home parity):
 * Shipment summary (30 days) + Appointment management + right rail.
 * Loss & Damage Claims and Support tickets are intentionally omitted (no
 * data source yet; we never show placeholder numbers).
 * B2C-only users are redirected to the B2C dashboard.
 */
export default function B2BDashboardPage() {
  const { routeTo, tenant } = useTenant();
  const { canAccessB2C, canAccessB2B } = useUser();
  const router = useRouter();
  const shouldRedirectToB2C = canAccessB2C && !canAccessB2B;

  const summary = useDashboardSummary(
    ServiceFlow.B2B,
    shouldRedirectToB2C ? null : STAGE_SUMMARY_WINDOW_DAYS
  );

  useEffect(() => {
    if (shouldRedirectToB2C) router.replace(routeTo("/dashboard"));
  }, [shouldRedirectToB2C, router, routeTo]);

  if (shouldRedirectToB2C) return null;

  const stages: B2BStageSummary | null =
    summary.data && isB2BStages(summary.data.stages) ? summary.data.stages : null;

  return (
    <div className="mx-auto max-w-7xl space-y-5 pb-12">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Home</h1>
        <p className="text-sm text-muted-foreground">
          B2B Part Truckload overview{tenant?.name ? ` for ${tenant.name}` : ""}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-5">
          <B2BShipmentSummary
            stages={stages}
            isLoading={summary.isLoading}
            error={summary.error}
            onRetry={summary.retry}
          />
          <AppointmentManagement
            appointments={summary.data?.appointments}
            isLoading={summary.isLoading}
            error={summary.error}
            onRetry={summary.retry}
          />
        </div>
        <DashboardRightRail flow={ServiceFlow.B2B} />
      </div>
    </div>
  );
}
