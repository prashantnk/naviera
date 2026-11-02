// frontend/src/components/dashboard/b2c-order-summary.tsx
"use client";

import type { B2CStageSummary } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { CheckCircle2, ClipboardList, Plus, Truck } from "lucide-react";
import Link from "next/link";

import { hasNoStageActivity, STAGE_SUMMARY_WINDOW_DAYS } from "./dashboard-model";
import { DashboardErrorState, DashboardSection } from "./dashboard-section";
import { StageCard, StageCardSkeleton, StageTile } from "./stage-card";

/** Destinations of each B2C stage tile. */
const B2C_ROUTES = {
  shipments: "/shipments",
  pickupRequests: "/pickup-requests",
  deliveryExceptions: "/delivery-exceptions",
  newForward: "/shipments/new/forward",
} as const;

interface B2COrderSummaryProps {
  stages: B2CStageSummary | null;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

/**
 * B2C "Order summary — last 30 days": Pre-Shipping · In Transit · Delivered/RTO.
 */
export function B2COrderSummary({ stages, isLoading, error, onRetry }: B2COrderSummaryProps) {
  const { routeTo } = useTenant();
  const canBook = useUser().capabilities.canBook;

  return (
    <DashboardSection
      headingId="dashboard-order-summary-heading"
      title="Order summary"
      description={`Orders created in the last ${STAGE_SUMMARY_WINDOW_DAYS} days`}
    >
      {error && !isLoading ? (
        <DashboardErrorState message={error} onRetry={onRetry} />
      ) : !stages ? (
        <div aria-label="Loading order summary" className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <StageCardSkeleton tiles={2} />
          <StageCardSkeleton tiles={2} />
          <StageCardSkeleton tiles={2} />
        </div>
      ) : (
        <div className="space-y-3">
          {hasNoStageActivity(stages) && (
            <div className="flex flex-col gap-3 rounded-lg border border-dashed bg-muted/30 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  No orders in the last {STAGE_SUMMARY_WINDOW_DAYS} days
                </p>
                <p className="text-xs text-muted-foreground">
                  Create a forward shipment and it will show up here.
                </p>
              </div>
              {canBook && (
                <Button asChild size="sm" className="shrink-0">
                  <Link href={routeTo(B2C_ROUTES.newForward)}>
                    <Plus className="mr-1 h-3.5 w-3.5" aria-hidden />
                    Forward shipment
                  </Link>
                </Button>
              )}
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <StageCard title="Pre-Shipping" icon={ClipboardList}>
              <StageTile label="To be shipped" count={stages.to_be_shipped} href={routeTo(`${B2C_ROUTES.shipments}?status=OPEN`)} />
              <StageTile
                label="Awaiting pickup"
                count={stages.awaiting_pickup}
                href={routeTo(B2C_ROUTES.pickupRequests)}
              />
            </StageCard>
            <StageCard title="In Transit" icon={Truck}>
              <StageTile label="In transit" count={stages.in_transit} href={routeTo(`${B2C_ROUTES.shipments}?status=IN_TRANSIT`)} />
              <StageTile
                label="NDR & exceptions"
                count={stages.ndr_exceptions}
                href={routeTo(B2C_ROUTES.deliveryExceptions)}
                hint="Failed delivery attempts and other exceptions that need your action"
              />
            </StageCard>
            <StageCard title="Delivered / RTO" icon={CheckCircle2}>
              <StageTile label="Delivered" count={stages.delivered} href={routeTo(`${B2C_ROUTES.shipments}?status=COMPLETED`)} />
              <StageTile label="RTO" count={stages.rto} href={routeTo(`${B2C_ROUTES.shipments}?status=RTO_INITIATED,RTO_IN_TRANSIT,RTO_DELIVERED`)} />
            </StageCard>
          </div>
        </div>
      )}
    </DashboardSection>
  );
}
