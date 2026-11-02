// frontend/src/components/dashboard/explore-services-card.tsx
"use client";

import { useUser } from "@/components/auth/auth-guard";
import { RequestB2bAccessDialog } from "@/components/blocks/request-b2b-dialog";
import { useWorkspaceFlow } from "@/components/providers/workspace-flow-provider";
import { ServiceFlow } from "@/lib/workspace-flow";
import { ChevronRight, Package, Truck, type LucideIcon } from "lucide-react";
import { useState } from "react";

interface FlowServiceMeta {
  name: string;
  description: string;
  icon: LucideIcon;
}

/** Marketing name + blurb for each flow (Delhivery "Explore other services"). */
const FLOW_SERVICE_META: Record<ServiceFlow, FlowServiceMeta> = {
  [ServiceFlow.B2C]: {
    name: "B2C Express Parcel",
    description: "Door-to-door parcels with COD and returns",
    icon: Package,
  },
  [ServiceFlow.B2B]: {
    name: "B2B Part Truckload",
    description: "LR-based cargo with pickups and appointments",
    icon: Truck,
  },
};

/** The flow a user is NOT currently in. */
const OTHER_FLOW: Record<ServiceFlow, ServiceFlow> = {
  [ServiceFlow.B2C]: ServiceFlow.B2B,
  [ServiceFlow.B2B]: ServiceFlow.B2C,
};

/**
 * "Explore other services" card.
 * - For users with access to both flows: shows `Active` badge and switches flow.
 * - For B2C-only customers: shows `B2B Part Truckload` with `Request Access` (or
 *   `Pending Approval`) and opens the B2B Access Request modal.
 *
 * @param flow - Flow of the dashboard currently shown.
 */
export function ExploreServicesCard({ flow }: { flow: ServiceFlow }) {
  const { canSwitchFlow, switchFlow } = useWorkspaceFlow();
  const { user, canAccessB2B } = useUser();
  const [requestDialogOpen, setRequestDialogOpen] = useState(false);

  const targetFlow = OTHER_FLOW[flow];
  if (!canSwitchFlow && targetFlow !== ServiceFlow.B2B) return null;

  const meta = FLOW_SERVICE_META[targetFlow];
  const Icon = meta.icon;
  const isB2bPending = !canAccessB2B && user?.b2b_request_status === "PENDING";

  const handleClick = () => {
    if (canSwitchFlow) {
      switchFlow(targetFlow);
      return;
    }
    setRequestDialogOpen(true);
  };

  return (
    <section aria-labelledby="dashboard-explore-heading" className="rounded-xl border bg-card p-4 shadow-sm">
      <h2 id="dashboard-explore-heading" className="mb-3 text-sm font-semibold text-foreground">
        Explore other services
      </h2>
      <button
        type="button"
        onClick={handleClick}
        className="group flex w-full items-center gap-3 rounded-lg border bg-card px-3 py-2.5 text-left outline-none transition-colors hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
          <Icon className="h-4.5 w-4.5 text-primary" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-foreground">{meta.name}</span>
            {canSwitchFlow ? (
              <span className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-px text-[10px] font-semibold text-emerald-700">
                Active
              </span>
            ) : isB2bPending ? (
              <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-px text-[10px] font-semibold text-amber-700">
                Pending Approval
              </span>
            ) : (
              <span className="rounded border border-primary/20 bg-primary/10 px-1.5 py-px text-[10px] font-semibold text-primary">
                Request Access
              </span>
            )}
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
            {meta.description}
          </span>
        </span>
        <ChevronRight
          className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
          aria-hidden
        />
      </button>

      {!canSwitchFlow && (
        <RequestB2bAccessDialog
          open={requestDialogOpen}
          onOpenChange={setRequestDialogOpen}
        />
      )}
    </section>
  );
}
