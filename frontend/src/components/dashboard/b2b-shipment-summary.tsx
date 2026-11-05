// frontend/src/components/dashboard/b2b-shipment-summary.tsx
"use client";

import type { B2BStageSummary, DashboardAppointments } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { CheckCircle2, ChevronRight, ClipboardList, Plus, Truck } from "lucide-react";
import Link from "next/link";

import { formatCountMetric, hasNoStageActivity, STAGE_SUMMARY_WINDOW_DAYS } from "./dashboard-model";
import { DashboardErrorState, DashboardSection, SkeletonBlock } from "./dashboard-section";
import { MetricTile } from "./metric-tile";
import { StageCard, StageCardSkeleton, StageQuickLink, StageTile } from "./stage-card";

/** Destinations of each B2B stage tile / quick link. */
const B2B_ROUTES = {
  shipments: "/b2b/shipments",
  newPickupRequest: "/b2b/pickup-requests/new",
  deliveryExceptions: "/b2b/delivery-exceptions",
  newForward: "/b2b/shipments/new/forward",
} as const;

interface B2BShipmentSummaryProps {
  stages: B2BStageSummary | null;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

/**
 * B2B "Shipment summary — last 30 days":
 * Pre-Dispatch · In Transit · Delivered / Returned.
 */
export function B2BShipmentSummary({ stages, isLoading, error, onRetry }: B2BShipmentSummaryProps) {
  const { routeTo } = useTenant();
  const canBook = useUser().capabilities.canBook;

  return (
    <DashboardSection
      headingId="dashboard-shipment-summary-heading"
      title="Shipment summary"
      description={`LRs created in the last ${STAGE_SUMMARY_WINDOW_DAYS} days`}
    >
      {error && !isLoading ? (
        <DashboardErrorState message={error} onRetry={onRetry} />
      ) : !stages ? (
        <div aria-label="Loading shipment summary" className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <StageCardSkeleton tiles={1} />
          <StageCardSkeleton tiles={2} />
          <StageCardSkeleton tiles={2} />
        </div>
      ) : (
        <div className="space-y-3">
          {hasNoStageActivity(stages) && (
            <div className="flex flex-col gap-3 rounded-lg border border-dashed bg-muted/30 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  No LRs in the last {STAGE_SUMMARY_WINDOW_DAYS} days
                </p>
                <p className="text-xs text-muted-foreground">
                  Book forward cargo and it will show up here.
                </p>
              </div>
              {canBook && (
                <Button asChild size="sm" className="shrink-0">
                  <Link href={routeTo(B2B_ROUTES.newForward)}>
                    <Plus className="mr-1 h-3.5 w-3.5" aria-hidden />
                    Book forward cargo
                  </Link>
                </Button>
              )}
            </div>
          )}
          <div className="grid grid-cols-1 items-start gap-3 md:grid-cols-3">
            <StageCard title="Pre-Dispatch" icon={ClipboardList}>
              <StageTile
                label="LRs manifested"
                count={stages.lrs_manifested}
                href={routeTo(`${B2B_ROUTES.shipments}?status=OPEN,ASSIGNED`)}
                footer={
                  canBook ? (
                    <StageQuickLink href={routeTo(B2B_ROUTES.newPickupRequest)} label="Create PUR" />
                  ) : undefined
                }
              />
            </StageCard>
            <StageCard title="In Transit" icon={Truck}>
              <StageTile label="In transit" count={stages.in_transit} href={routeTo(`${B2B_ROUTES.shipments}?status=IN_TRANSIT`)} />
              <StageTile
                label="Appointment, NDR & other exceptions"
                count={stages.exceptions}
                href={routeTo(B2B_ROUTES.deliveryExceptions)}
                footer={
                  <StageQuickLink
                    href={routeTo(B2B_ROUTES.deliveryExceptions)}
                    label="Consignee unreachable"
                    count={stages.consignee_unreachable}
                  />
                }
              />
            </StageCard>
            <StageCard
              title="Delivered / Returned"
              icon={CheckCircle2}
              footer={
                <>
                  <StageQuickLink href={routeTo(`${B2B_ROUTES.shipments}?status=IN_TRANSIT`)} label="View in-transit" count={stages.in_transit} />
                  <StageQuickLink href={routeTo(`${B2B_ROUTES.shipments}?status=RTO_INITIATED,RTO_IN_TRANSIT,RTO_DELIVERED`)} label="View returned" count={stages.rto} />
                </>
              }
            >
              <StageTile label="Delivered" count={stages.delivered} href={routeTo(`${B2B_ROUTES.shipments}?status=COMPLETED`)} />
              <StageTile label="RTO" count={stages.rto} href={routeTo(`${B2B_ROUTES.shipments}?status=RTO_INITIATED,RTO_IN_TRANSIT,RTO_DELIVERED`)} />
            </StageCard>
          </div>
        </div>
      )}
    </DashboardSection>
  );
}

interface AppointmentManagementProps {
  appointments: DashboardAppointments | null | undefined;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

/** One appointment counter with its "View all" link. */
interface AppointmentTileMeta {
  key: keyof DashboardAppointments;
  label: string;
}

/** Appointment counters in display order. */
const APPOINTMENT_TILES: readonly AppointmentTileMeta[] = [
  { key: "needed", label: "Appointments needed" },
  { key: "at_risk", label: "Appointments at risk" },
  { key: "booked", label: "Appointments booked" },
];

/**
 * B2B "Appointment management": needed / at risk / booked. A `null` counter
 * means the backend cannot derive it yet and renders "—" with a tooltip.
 */
export function AppointmentManagement({ appointments, isLoading, error, onRetry }: AppointmentManagementProps) {
  const { routeTo } = useTenant();
  const viewAllHref = routeTo(B2B_ROUTES.deliveryExceptions);

  return (
    <DashboardSection headingId="dashboard-appointments-heading" title="Appointment management">
      {error && !isLoading ? (
        <DashboardErrorState message={error} onRetry={onRetry} />
      ) : isLoading && !appointments ? (
        <div aria-label="Loading appointments" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {APPOINTMENT_TILES.map((tile) => (
            <SkeletonBlock key={tile.key} className="h-16" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {APPOINTMENT_TILES.map((tile) => (
            <MetricTile
              key={tile.key}
              label={tile.label}
              formattedValue={formatCountMetric(appointments?.[tile.key])}
              footer={
                <Link
                  href={viewAllHref}
                  className="inline-flex shrink-0 items-center gap-0.5 rounded-sm text-[11px] font-medium text-foreground/80 outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={`View all ${tile.label.toLowerCase()}`}
                >
                  View all
                  <ChevronRight className="h-3 w-3" aria-hidden />
                </Link>
              }
            />
          ))}
        </div>
      )}
    </DashboardSection>
  );
}
