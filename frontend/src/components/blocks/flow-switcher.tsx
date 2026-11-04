// frontend/src/components/blocks/flow-switcher.tsx
"use client";

/**
 * Delhivery-style "Choose your flow" dropdown.
 *
 * Lets users with access to both services pick whether they are working in
 * B2C Express or B2B Cargo. Single-service users see the same block as a
 * read-only label so they always know which flow they are in.
 */
import { useUser } from "@/components/auth/auth-guard";
import { RequestB2bAccessDialog } from "@/components/blocks/request-b2b-dialog";
import { useTenant } from "@/components/providers/tenant-provider";
import { useWorkspaceFlow } from "@/components/providers/workspace-flow-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { ServiceFlow } from "@/lib/workspace-flow";
import { Check, ChevronDown, Package, Truck, type LucideIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

interface FlowOption {
  flow: ServiceFlow;
  label: string;
  description: string;
  icon: LucideIcon;
  /** Tinted tile classes (semantic palette, never tenant brand colours). */
  tileClassName: string;
}

const FLOW_OPTIONS: Record<ServiceFlow, FlowOption> = {
  [ServiceFlow.B2C]: {
    flow: ServiceFlow.B2C,
    label: "B2C Express",
    description: "Domestic parcels · Forward & DTO",
    icon: Package,
    tileClassName: "bg-sky-100 text-sky-700 border-sky-200",
  },
  [ServiceFlow.B2B]: {
    flow: ServiceFlow.B2B,
    label: "B2B Cargo",
    description: "Heavy cargo · LTL / Surface freight",
    icon: Truck,
    tileClassName: "bg-amber-100 text-amber-700 border-amber-200",
  },
};

/** Display order of options inside the dropdown. */
const FLOW_ORDER: readonly ServiceFlow[] = [ServiceFlow.B2C, ServiceFlow.B2B];

type FlowSwitcherVariant = "header" | "drawer";

interface FlowSwitcherProps {
  /** `header` = light top bar (compact on mobile); `drawer` = dark mobile drawer. */
  variant: FlowSwitcherVariant;
}

/**
 * Renders the coloured icon tile for a flow.
 *
 * @param option - Flow option to render.
 * @param size - Tailwind size classes for the tile.
 */
function FlowTile({ option, size }: { option: FlowOption; size: string }) {
  const Icon = option.icon;
  return (
    <div
      className={cn(
        "rounded-lg border flex items-center justify-center shrink-0",
        option.tileClassName,
        size
      )}
    >
      <Icon className="h-4 w-4" />
    </div>
  );
}

/**
 * Text block (title + subtitle) shown on the trigger.
 *
 * @param option - Active flow option.
 * @param subtitle - Secondary line (tenant name on desktop header).
 * @param isDark - Whether the block sits on the dark drawer background.
 */
function FlowTriggerText({
  option,
  subtitle,
  isDark,
}: {
  option: FlowOption;
  subtitle: string;
  isDark: boolean;
}) {
  return (
    <div className="min-w-0 text-left leading-tight">
      <p
        className={cn(
          "text-sm font-bold truncate",
          isDark ? "text-slate-100" : "text-slate-900"
        )}
      >
        {option.label}
      </p>
      <p
        className={cn(
          "text-[11px] truncate",
          isDark ? "text-slate-400" : "text-slate-500"
        )}
      >
        {subtitle}
      </p>
    </div>
  );
}

export function FlowSwitcher({ variant }: FlowSwitcherProps) {
  const { tenant, tenantSlug, routeTo } = useTenant();
  const { activeFlow, canSwitchFlow, switchFlow } = useWorkspaceFlow();
  const { user, canAccessB2B } = useUser();
  const router = useRouter();
  const [requestB2bOpen, setRequestB2bOpen] = useState(false);

  useEffect(() => {
    router.prefetch(routeTo("/dashboard"));
    if (canAccessB2B) {
      router.prefetch(routeTo("/b2b/dashboard"));
    }
  }, [router, routeTo, canAccessB2B]);

  const activeOption = FLOW_OPTIONS[activeFlow];
  const isDrawer = variant === "drawer";
  const subtitle = `${tenant?.name || tenantSlug} · ${
    activeFlow === ServiceFlow.B2B ? "Cargo" : "Parcels"
  }`;

  const containerClassName = cn(
    "flex items-center gap-1 sm:gap-2.5 rounded-xl border transition-colors",
    isDrawer
      ? "w-full p-2.5 bg-slate-900 border-slate-800"
      : "h-9 sm:h-11 px-1.5 lg:px-2.5 bg-white border-slate-200 lg:w-[240px]"
  );
  const textClassName = isDrawer ? "flex-1 min-w-0" : "hidden lg:block flex-1 min-w-0";

  const handleSelect = (flow: ServiceFlow) => {
    if (flow === activeFlow) return;
    if (flow === ServiceFlow.B2B && !canAccessB2B) {
      setRequestB2bOpen(true);
      return;
    }
    if (!canSwitchFlow) return;
    switchFlow(flow);
    toast.success(`Switched to ${FLOW_OPTIONS[flow].label}`);
  };

  const isB2bPending = !canAccessB2B && user?.b2b_request_status === "PENDING";

  // B2B-only single-service users: read-only label.
  if (!canSwitchFlow && canAccessB2B) {
    return (
      <div className={containerClassName} aria-label={`Current flow: ${activeOption.label}`}>
        <FlowTile option={activeOption} size="h-8 w-8" />
        <div className={textClassName}>
          <FlowTriggerText option={activeOption} subtitle={subtitle} isDark={isDrawer} />
        </div>
      </div>
    );
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Current flow: ${activeOption.label}. Switch flow`}
            className={cn(
              containerClassName,
              "cursor-pointer",
              isDrawer
                ? "hover:border-slate-700"
                : "hover:border-primary/30 hover:bg-slate-50 shadow-2xs"
            )}
          >
            <FlowTile option={activeOption} size="h-8 w-8" />
            <div className={textClassName}>
              <FlowTriggerText option={activeOption} subtitle={subtitle} isDark={isDrawer} />
            </div>
            <ChevronDown
              className={cn(
                "h-4 w-4 shrink-0",
                isDrawer ? "text-slate-400" : "text-slate-400 lg:ml-auto"
              )}
            />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align={isDrawer ? "start" : "end"}
          className="w-[300px] rounded-2xl p-2 shadow-xl border-slate-200"
        >
          <DropdownMenuLabel className="px-2 pt-1 pb-2 text-[10px] font-bold uppercase tracking-widest text-slate-400">
            Choose your flow
          </DropdownMenuLabel>
          {FLOW_ORDER.map((flow) => {
            const option = FLOW_OPTIONS[flow];
            const isActive = flow === activeFlow;
            const requiresB2bRequest = flow === ServiceFlow.B2B && !canAccessB2B;
            return (
              <DropdownMenuItem
                key={flow}
                onSelect={() => handleSelect(flow)}
                className={cn(
                  "cursor-pointer rounded-xl p-2.5 gap-3",
                  isActive && "bg-slate-50"
                )}
              >
                <FlowTile option={option} size="h-10 w-10" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <p className="text-sm font-bold text-slate-900">{option.label}</p>
                    {requiresB2bRequest && (
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-semibold border",
                          isB2bPending
                            ? "bg-amber-50 text-amber-700 border-amber-200"
                            : "bg-primary/10 text-primary border-primary/20"
                        )}
                      >
                        {isB2bPending ? "Pending" : "Request Access"}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 leading-snug">{option.description}</p>
                </div>
                {isActive && <Check className="h-4 w-4 text-primary shrink-0" />}
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>

      {!canAccessB2B && (
        <RequestB2bAccessDialog
          open={requestB2bOpen}
          onOpenChange={setRequestB2bOpen}
        />
      )}
    </>
  );
}
