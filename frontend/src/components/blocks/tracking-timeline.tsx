// frontend/src/components/blocks/tracking-timeline.tsx
import { PublicActivityRead, PublicTrackingRead } from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { getShipmentStatusBadgeClass } from "@/components/shipments/shipment-stage";
import { cn, parseUtcDate } from "@/lib/utils";
import {
  AlertCircle,
  CheckCircle2,
  MapPin,
  Package,
  Truck,
} from "lucide-react";
import { CopyTrackingId } from "@/components/tracking/copy-tracking-id";
import { CarrierInfo } from "@/components/carrier/carrier-info";
import { ShipmentPodBanner } from "@/components/wallet/shipment-pod-controls";
import {
  PublicTrackingStep,
  TrackingStepTone,
  buildPublicTrackingSteps,
  contiguousProgressIndex,
  friendlyActivityTitle,
  getPublicStatusLabel,
} from "@/components/blocks/tracking-display";

/** Buyers are in India: show IST dates/times whatever the device timezone. */
const DISPLAY_LOCALE = "en-IN";
const DISPLAY_TIME_ZONE = "Asia/Kolkata";

/** Icon + colours for one timeline event, chosen from its (friendly) title. */
interface EventStyling {
  bg: string;
  text: string;
  Icon: typeof Package;
}

const ALERT_STYLING: EventStyling = {
  bg: "bg-destructive/10",
  text: "text-destructive",
  Icon: AlertCircle,
};

/** Keyword groups, checked in order; the first match decides the icon. */
const EVENT_STYLING_RULES: ReadonlyArray<{ keywords: string[]; styling: EventStyling }> = [
  { keywords: ["returned", "rto"], styling: ALERT_STYLING },
  {
    keywords: ["delivered"],
    styling: { bg: "bg-primary/10", text: "text-primary", Icon: CheckCircle2 },
  },
  {
    keywords: ["transit", "out for delivery", "picked up"],
    styling: { bg: "bg-primary/10", text: "text-primary", Icon: Truck },
  },
  {
    keywords: ["warehouse", "facility", "pickup"],
    styling: { bg: "bg-primary/10", text: "text-primary", Icon: MapPin },
  },
  {
    keywords: ["cancelled", "issue", "exception", "failed", "rejected", "lost"],
    styling: ALERT_STYLING,
  },
];

const DEFAULT_STYLING: EventStyling = {
  bg: "bg-primary/10",
  text: "text-primary",
  Icon: Package,
};

/**
 * Picks the timeline icon for an event title.
 *
 * @param title - Friendly event title (already passed through `friendlyActivityTitle`).
 * @returns Icon and colour classes.
 */
function getEventStyling(title: string): EventStyling {
  const lower = title.toLowerCase();
  const rule = EVENT_STYLING_RULES.find(({ keywords }) =>
    keywords.some((keyword) => lower.includes(keyword))
  );
  return rule ? rule.styling : DEFAULT_STYLING;
}

function formatDate(isoString: string): string {
  const parsed = parseUtcDate(isoString);
  if (!parsed) return isoString;
  return parsed.toLocaleString(DISPLAY_LOCALE, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: DISPLAY_TIME_ZONE,
  });
}

function formatTime(isoString: string): string {
  const parsed = parseUtcDate(isoString);
  if (!parsed) return "";
  return parsed.toLocaleString(DISPLAY_LOCALE, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: DISPLAY_TIME_ZONE,
  });
}

/** Classes for a step's number bubble. */
function stepBubbleClass(step: PublicTrackingStep): string {
  if (!step.reached) return "bg-card border-muted text-muted-foreground";
  return step.tone === TrackingStepTone.ALERT
    ? "bg-destructive border-destructive text-destructive-foreground"
    : "bg-primary border-primary text-primary-foreground";
}

/**
 * The 5-step progress stepper: a vertical list on phones and a horizontal
 * bar from `sm` up, with wrapping labels so they never overlap (F-09).
 */
function TrackingStepper({ steps }: { steps: PublicTrackingStep[] }) {
  const progressIndex = contiguousProgressIndex(steps);
  const lastIndex = steps.length - 1;
  return (
    <ol data-testid="tracking.stepper" className="relative grid gap-4 sm:gap-2 sm:grid-cols-5">
      {/* Horizontal track lines (sm+ only), between the first and last bubble centres */}
      <div className="hidden sm:block absolute top-4 left-[10%] right-[10%] h-0.5 bg-muted rounded-full" />
      <div
        className="hidden sm:block absolute top-4 left-[10%] right-[10%] h-0.5 bg-primary rounded-full transition-transform duration-500 ease-in-out"
        style={{ transform: `scaleX(${progressIndex / lastIndex})`, transformOrigin: "left" }}
      />
      {steps.map((step, idx) => (
        <li
          key={step.label}
          data-testid={`tracking.step.${idx}`}
          data-reached={step.reached}
          className="relative z-10 flex sm:flex-col items-center gap-3 sm:gap-2 sm:text-center"
        >
          <span
            className={cn(
              "w-8 h-8 shrink-0 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 border-2",
              stepBubbleClass(step)
            )}
            aria-hidden="true"
          >
            {idx + 1}
          </span>
          <span
            className={cn(
              "text-sm sm:text-xs leading-tight",
              step.reached ? "text-foreground font-extrabold" : "text-muted-foreground font-bold"
            )}
          >
            {step.label}
            <span className="sr-only">{step.reached ? " (done)" : " (pending)"}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

export function TrackingTimeline({ data }: { data: PublicTrackingRead }) {
  const steps = buildPublicTrackingSteps(data.status);

  return (
    <div className="w-full max-w-2xl mx-auto bg-card rounded-xl shadow-sm border border-border overflow-hidden">
      {/* Header Section */}
      <div className="p-6 md:p-8 border-b border-border/50 flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-widest flex items-center gap-1.5 mb-2">
            <MapPin className="h-3.5 w-3.5" /> Tracking ID
          </p>
          <div className="flex items-center gap-3 min-w-0">
            <h2 className="text-2xl md:text-3xl font-extrabold text-foreground tracking-tight break-all">
              {data.tracking_id}
            </h2>
            <CopyTrackingId trackingId={data.tracking_id} />
          </div>
          <CarrierInfo
            carrierName={data.carrier_name}
            carrierAwb={data.carrier_awb}
            className="mt-2"
          />
        </div>

        <Badge
          variant="outline"
          data-testid="tracking.status-badge"
          className={cn(
            "text-sm px-4 py-1.5 w-fit rounded-full shadow-sm font-bold tracking-wider uppercase border",
            getShipmentStatusBadgeClass(data.status)
          )}
        >
          {getPublicStatusLabel(data.status)}
        </Badge>
      </div>

      {data.pod_received_by && (
        <div className="px-6 md:px-8 pt-4">
          <ShipmentPodBanner
            deliveryOtp={null}
            podReceivedBy={data.pod_received_by}
            status={data.status}
          />
        </div>
      )}

      {/* Stepper Section */}
      <div className="px-6 md:px-8 py-8 border-b border-border/50">
        <TrackingStepper steps={steps} />
      </div>

      {/* Timeline Section */}
      <div className="p-6 md:p-8">
        <div className="relative border-l-2 border-muted ml-4 space-y-10 pb-4">
          {(!data.timeline || data.timeline.length === 0) && (
            <div className="pl-8 text-muted-foreground italic">
              Tracking details will appear here shortly.
            </div>
          )}

          {data.timeline?.map((event: PublicActivityRead, index: number) => {
            const title = friendlyActivityTitle(event.status_title);
            const style = getEventStyling(title);
            const Icon = style.Icon;

            return (
              <div key={index} className="relative pl-8 md:pl-10 group">
                {/* The Timeline Dot masked by ring-card */}
                <div
                  className={cn(
                    "absolute -left-[17px] top-0 h-8 w-8 rounded-full ring-8 ring-card flex items-center justify-center transition-transform group-hover:scale-110",
                    style.bg,
                    style.text
                  )}
                >
                  <Icon className="h-4 w-4 stroke-[2.5px]" />
                </div>

                {/* The Content */}
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-baseline gap-2 pt-1">
                  <h3 className="text-base font-bold text-foreground">{title}</h3>
                  <div className="flex sm:flex-col gap-2 sm:gap-0 sm:text-right text-sm font-medium text-muted-foreground">
                    <span className="text-foreground/80">
                      {formatTime(event.timestamp)}
                    </span>
                    <span className="text-muted-foreground/60 sm:text-xs">
                      {formatDate(event.timestamp)}
                    </span>
                  </div>
                </div>

                {event.message && (
                  <p className="text-foreground/80 mt-2 text-sm max-w-md leading-relaxed bg-muted/40 p-3 rounded-lg border border-border/50">
                    {event.message}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer Section */}
      {data.estimated_delivery && (
        <div className="p-6 md:p-8 bg-muted/30 border-t border-border/50 flex justify-between items-center">
          <span className="text-sm font-medium text-muted-foreground uppercase tracking-widest">
            Estimated Delivery
          </span>
          <span className="text-base font-bold text-foreground">
            {formatDate(data.estimated_delivery)}
          </span>
        </div>
      )}
    </div>
  );
}
