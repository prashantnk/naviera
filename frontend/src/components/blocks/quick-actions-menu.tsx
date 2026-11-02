// frontend/src/components/blocks/quick-actions-menu.tsx
"use client";

/**
 * Delhivery One-style "Quick Actions" header menu.
 *
 * Offers the three everyday jobs for the currently active flow:
 * book a shipment, request a pickup, and check rates. Items follow the
 * B2C Express ⇄ B2B Cargo flow chosen in the header switcher.
 */
import { useTenant } from "@/components/providers/tenant-provider";
import { useWorkspaceFlow } from "@/components/providers/workspace-flow-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { B2B_REVERSE_BOOKING_ENABLED } from "@/lib/mvp-scope";
import { ServiceFlow } from "@/lib/workspace-flow";
import {
  ArrowUpRight,
  Calculator,
  RotateCcw,
  Truck,
  Zap,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useUser } from "@/components/auth/auth-guard";

interface QuickAction {
  label: string;
  description: string;
  href: string;
  icon: LucideIcon;
  /** Booking actions are hidden for roles that cannot book (support / read-only staff). */
  requiresBooking?: boolean;
}

/** Quick actions per flow (tenant-relative routes, resolved via `routeTo`). */
const QUICK_ACTIONS: Record<ServiceFlow, QuickAction[]> = {
  [ServiceFlow.B2C]: [
    {
      label: "Create Forward Shipment",
      description: "Book a parcel to your customer",
      href: "/shipments/new/forward",
      requiresBooking: true,
      icon: ArrowUpRight,
    },
    {
      label: "Create Reverse Shipment",
      description: "Pick up a return from your customer",
      href: "/shipments/new/reverse",
      requiresBooking: true,
      icon: RotateCcw,
    },
    {
      label: "Create Pickup Request",
      description: "Schedule collection of Ready to Ship parcels",
      href: "/pickup-requests/new",
      requiresBooking: true,
      icon: Truck,
    },
    {
      label: "Rate Calculator",
      description: "Check price, TAT and serviceability",
      href: "/rate-calculator",
      icon: Calculator,
    },
  ],
  [ServiceFlow.B2B]: [
    {
      label: "Book Forward Cargo",
      description: "Create and manifest a B2B LR",
      href: "/b2b/shipments/new/forward",
      requiresBooking: true,
      icon: ArrowUpRight,
    },
    // B2B reverse LRs are off for the MVP (WP0).
    ...(B2B_REVERSE_BOOKING_ENABLED
      ? [
          {
            label: "B2B Return / Pickup",
            description: "Book a reverse cargo movement",
            href: "/b2b/shipments/new/reverse",
            requiresBooking: true,
            icon: RotateCcw,
          },
        ]
      : []),
    {
      label: "Create Pickup Request",
      description: "Schedule a truck for manifested LRs",
      href: "/b2b/pickup-requests/new",
      requiresBooking: true,
      icon: Truck,
    },
    {
      label: "Rate Calculator",
      description: "Serviceability and freight estimate",
      href: "/b2b/rate-calculator",
      icon: Calculator,
    },
  ],
};

export function QuickActionsMenu() {
  const { routeTo } = useTenant();
  const { activeFlow } = useWorkspaceFlow();
  const { capabilities } = useUser();
  const actions = QUICK_ACTIONS[activeFlow].filter(
    (action) => !action.requiresBooking || capabilities.canBook
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Quick Actions"
          className="h-9 pl-1 pr-1 sm:pr-3 rounded-full border border-slate-200 bg-white flex items-center gap-2 text-sm font-semibold text-slate-700 hover:border-primary/30 hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
        >
          <span className="h-7 w-7 rounded-full bg-slate-900 text-white flex items-center justify-center shrink-0">
            <Zap className="h-3.5 w-3.5" />
          </span>
          <span className="hidden sm:inline">Quick Actions</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[300px] rounded-2xl p-2 shadow-xl border-slate-200">
        <DropdownMenuLabel className="px-2 pt-1 pb-2 text-[10px] font-bold uppercase tracking-widest text-slate-400">
          Quick Actions
        </DropdownMenuLabel>
        {actions.map((action) => (
          <DropdownMenuItem key={action.href} asChild className="cursor-pointer rounded-xl p-2.5 gap-3">
            <Link href={routeTo(action.href)} className="flex items-center">
              <span className="h-9 w-9 rounded-lg bg-primary/10 text-primary border border-primary/20 flex items-center justify-center shrink-0">
                <action.icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-bold text-slate-900">{action.label}</span>
                <span className="block text-xs text-slate-500 leading-snug">{action.description}</span>
              </span>
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
