// frontend/src/components/pickups/order-columns.tsx
"use client";

/**
 * Delhivery One "Orders" grid, shared by B2C `/shipments` and B2B `/b2b/shipments`.
 *
 * Columns: AWB & Order ID · Manifested date · Pickup & delivery (2-stop mini
 * timeline) · Transport & zone · Payment mode · row actions. Row actions follow
 * the status: Ready to ship → "Add to pickup"; Delivered → "Print POD" +
 * "Initiate return"; every row has a "⋯" menu.
 *
 * Purely presentational: every number shown (COD amount, box count) comes from
 * the API payload; nothing is computed here.
 */
import {
  FreightPaymentMode,
  PickupStatus,
  ServiceType,
  ShipmentType,
  type PickupRead,
} from "@/api_client";
import { buildCreatePickupHref } from "@/components/pickups/pickup-constants";
import {
  buildSelectionColumn,
  type RowSelectionOptions,
} from "@/components/pickups/selection-column";
import { getShipmentStatusLabel } from "@/components/pickups/status-display";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { downloadShipmentInvoicePdf, downloadShippingLabel } from "@/lib/api";
import { FREIGHT_PAYMENT_MODE_OPTIONS } from "@/lib/form-options";
import { B2B_REVERSE_BOOKING_ENABLED } from "@/lib/mvp-scope";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { cn, extractApiErrorMessage, parseUtcDate, safeFormatDate } from "@/lib/utils";
import { ServiceFlow } from "@/lib/workspace-flow";
import type { ColumnDef } from "@tanstack/react-table";
import {
  ArrowUpDown,
  ExternalLink,
  Eye,
  FileText,
  Loader2,
  MoreHorizontal,
  Plane,
  Printer,
  RotateCcw,
  Truck,
} from "lucide-react";
import Link from "next/link";
import { useProgressRouter } from "@/hooks/use-progress-router";
import { type MouseEvent } from "react";
import { toast } from "sonner";

/** Delhivery transport labels: Air = EXPRESS, road/rail = SURFACE. */
export const TRANSPORT_MODE_LABEL: Readonly<Record<ServiceType, string>> = {
  [ServiceType.AIR]: "EXPRESS",
  [ServiceType.SURFACE_ROAD]: "SURFACE",
  [ServiceType.SURFACE_TRAIN]: "SURFACE",
};

/** Date formats used in the grid. */
const MANIFEST_DATE_FORMAT = "dd MMM, yyyy";
const MANIFEST_TIME_FORMAT = "h:mmaaa";

/** Flow-specific copy and routes for the Orders grid. */
export interface OrdersFlowCopy {
  flow: ServiceFlow;
  /** "AWB" (parcels) or "LRN" (cargo). */
  idNoun: string;
  /** Tenant-relative orders base path, e.g. `/shipments`. */
  basePath: string;
  /** Tenant-relative reverse booking path; null when reverse booking is off for the flow. */
  reverseHref: string | null;
  /** Whether the reverse wizard can prefill from a forward shipment. */
  reverseSupportsPrefill: boolean;
}

/** Copy/routes per flow. */
export const ORDERS_FLOW_COPY: Readonly<Record<ServiceFlow, OrdersFlowCopy>> = {
  [ServiceFlow.B2C]: {
    flow: ServiceFlow.B2C,
    idNoun: "AWB",
    basePath: "/shipments",
    reverseHref: "/shipments/new/reverse",
    reverseSupportsPrefill: true,
  },
  [ServiceFlow.B2B]: {
    flow: ServiceFlow.B2B,
    idNoun: "LRN",
    basePath: "/b2b/shipments",
    // B2B reverse LRs are off for the MVP (WP0).
    reverseHref: B2B_REVERSE_BOOKING_ENABLED ? "/b2b/shipments/new/reverse" : null,
    reverseSupportsPrefill: false,
  },
};

/** What the current user may do from a row (from `useUser().capabilities`). */
export interface OrderRowPermissions {
  /** Create pickups / bookings (Add to pickup, Initiate return). */
  canBook: boolean;
}

/**
 * Formats an ISO timestamp as Delhivery's two-line manifested date.
 *
 * @param iso - ISO timestamp from the API.
 * @returns Date and time strings, or null when the value is missing/invalid.
 */
export function formatManifestedDate(
  iso: string | null | undefined
): { date: string; time: string } | null {
  // Naive API timestamps are UTC; show them in IST like the rest of the app (F-02).
  if (!parseUtcDate(iso)) return null;
  return {
    date: safeFormatDate(iso, MANIFEST_DATE_FORMAT),
    time: safeFormatDate(iso, MANIFEST_TIME_FORMAT),
  };
}

/**
 * Payment mode label for a row: B2C shows COD/Prepaid, B2B shows the freight mode.
 *
 * @param shipment - Row data.
 * @param flow - Active flow.
 * @returns Primary label and an optional COD amount (as sent by the API).
 */
export function getPaymentModeDisplay(
  shipment: PickupRead,
  flow: ServiceFlow
): { label: string; codAmount: number | null } {
  const details = shipment.payment_details;
  const isCod = Boolean(details?.is_cod);
  const codAmount = isCod ? details?.cod_amount ?? null : null;
  if (flow === ServiceFlow.B2B && details?.freight_payment_mode) {
    const mode = details.freight_payment_mode as FreightPaymentMode;
    return { label: FREIGHT_PAYMENT_MODE_OPTIONS[mode]?.label ?? mode, codAmount };
  }
  return { label: isCod ? "COD" : "Prepaid", codAmount };
}

/**
 * Builds the tenant-relative "Initiate return" link for a delivered row.
 *
 * @param shipment - Row data.
 * @param copy - Flow copy.
 * @returns Reverse booking href (prefilled when supported), or null when returns are off.
 */
export function buildInitiateReturnHref(shipment: PickupRead, copy: OrdersFlowCopy): string | null {
  if (!copy.reverseHref) return null;
  return copy.reverseSupportsPrefill
    ? `${copy.reverseHref}?from_shipment_id=${shipment.id}`
    : copy.reverseHref;
}

/** Stops row clicks from opening the order when a nested control is used. */
function _stop(event: MouseEvent) {
  event.stopPropagation();
}

interface OrderRowActionsProps {
  shipment: PickupRead;
  copy: OrdersFlowCopy;
  permissions: OrderRowPermissions;
  /** Compact (mobile card) layout. */
  compact?: boolean;
}

/** Status-aware row actions (Delhivery: Add to pickup / Print POD / Initiate return + ⋯). */
export function OrderRowActions({ shipment, copy, permissions, compact }: OrderRowActionsProps) {
  const router = useProgressRouter();
  const { routeTo, tenantSlug } = useTenant();
  const { pending: printingPod, run: runPrintPod } = useSingleFlight();
  const { pending: printingLabel, run: runPrintLabel } = useSingleFlight();

  const isReadyToShip = shipment.status === PickupStatus.OPEN;
  const isDelivered = shipment.status === PickupStatus.COMPLETED;
  const isForward = shipment.shipment_type === ShipmentType.FORWARD;
  const addToPickupHref = routeTo(
    buildCreatePickupHref(copy.flow, {
      locationId: shipment.pickup_address?.id,
      shipmentIds: [shipment.id],
    })
  );
  const returnPath = buildInitiateReturnHref(shipment, copy);
  const initiateReturnHref = returnPath ? routeTo(returnPath) : null;
  const detailsHref = routeTo(`${copy.basePath}/${shipment.id}`);
  const showAddToPickup = permissions.canBook && isReadyToShip;
  const showReturn = permissions.canBook && isDelivered && isForward && initiateReturnHref !== null;

  const handlePrintPod = () =>
    runPrintPod(async () => {
      try {
        await downloadShipmentInvoicePdf(shipment.id, shipment.tracking_id);
        toast.success("POD downloaded.");
      } catch (err) {
        toast.error(extractApiErrorMessage(err, "Failed to download POD."));
      }
    });

  const handlePrintLabel = () =>
    runPrintLabel(async () => {
      try {
        await downloadShippingLabel(tenantSlug, shipment.id, shipment.tracking_id || shipment.id);
        toast.success("Shipping label downloaded.");
      } catch (err) {
        toast.error(extractApiErrorMessage(err, "Failed to generate shipping label."));
      }
    });

  const buttonClass = cn(
    "text-xs font-semibold border-slate-300 bg-white text-slate-800 hover:bg-slate-50",
    compact ? "h-8 px-2.5" : "h-8 px-3"
  );

  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2",
        compact ? "flex-wrap" : "ml-auto max-w-[220px] flex-wrap"
      )}
      onClick={_stop}
    >
      {showAddToPickup && (
        <Button variant="outline" size="sm" asChild className={buttonClass}>
          <Link href={addToPickupHref}>
            Add to pickup
            <Truck className="ml-1.5 h-3.5 w-3.5" />
          </Link>
        </Button>
      )}
      {isDelivered && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={printingPod}
          onClick={handlePrintPod}
          className={buttonClass}
        >
          {printingPod ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Printer className="mr-1.5 h-3.5 w-3.5" />
          )}
          Print POD
        </Button>
      )}
      {showReturn && initiateReturnHref && (
        <Button variant="outline" size="sm" asChild className={buttonClass}>
          <Link href={initiateReturnHref}>
            Initiate return
            <RotateCcw className="ml-1.5 h-3.5 w-3.5" />
          </Link>
        </Button>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="More order actions"
            aria-busy={printingLabel || printingPod}
            className="h-8 w-8 border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
          >
            {printingLabel || printingPod ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <MoreHorizontal className="h-4 w-4" />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem onClick={() => router.push(detailsHref)}>
            <Eye className="mr-2 h-4 w-4 text-slate-500" />
            View order details
          </DropdownMenuItem>
          <DropdownMenuItem disabled={printingLabel} onClick={handlePrintLabel}>
            <Printer className="mr-2 h-4 w-4 text-slate-500" />
            Print shipping label
          </DropdownMenuItem>
          <DropdownMenuItem disabled={printingPod} onClick={handlePrintPod}>
            <FileText className="mr-2 h-4 w-4 text-slate-500" />
            Download invoice
          </DropdownMenuItem>
          {shipment.tracking_id && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => router.push(routeTo(`/track/${shipment.tracking_id}`))}
              >
                <ExternalLink className="mr-2 h-4 w-4 text-slate-500" />
                Public tracking page
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

/** AWB/LRN link + order id (+ box count for cargo). */
export function OrderIdCell({ shipment, copy }: { shipment: PickupRead; copy: OrdersFlowCopy }) {
  const { routeTo } = useTenant();
  const isB2B = copy.flow === ServiceFlow.B2B;
  const boxes = shipment.total_box_count;
  return (
    <div className="flex min-w-0 max-w-[180px] flex-col">
      <Link
        href={routeTo(`${copy.basePath}/${shipment.id}`)}
        onClick={_stop}
        className="truncate font-mono text-sm font-semibold text-primary hover:underline"
      >
        {shipment.tracking_id || "Pending"}
      </Link>
      <span className="truncate text-xs text-slate-600">
        {shipment.order_reference_id || "No order ID"}
      </span>
      {isB2B && (
        <span className="text-[11px] text-slate-500">
          {boxes} {boxes === 1 ? "Box" : "Boxes"}
          {shipment.is_blind_pickup ? " · Blind" : ""}
        </span>
      )}
    </div>
  );
}

/** Two-stop mini timeline: pickup (hollow circle) → delivery (square). */
export function PickupDeliveryCell({ shipment }: { shipment: PickupRead }) {
  const origin = shipment.pickup_address;
  const destination = shipment.delivery_address;
  const originName = origin?.company_name || origin?.name || "Pickup";
  const destinationName = destination?.name || destination?.company_name || "Consignee";
  return (
    <div className="flex min-w-0 max-w-[220px] flex-col text-xs">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 shrink-0 rounded-full border-2 border-slate-700 bg-white" />
        <span className="truncate font-semibold uppercase text-slate-800">{originName}</span>
      </div>
      <div className="ml-[4.5px] border-l border-dashed border-slate-300 pl-3.5 text-slate-500">
        {[origin?.city, origin?.pincode].filter(Boolean).join(" ")}
      </div>
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 shrink-0 rounded-[2px] border-2 border-emerald-600 bg-white" />
        <span className="truncate font-semibold uppercase text-slate-800">{destinationName}</span>
      </div>
      <div className="pl-[18px] text-slate-500">
        {[destination?.city, destination?.pincode].filter(Boolean).join(" ")}
      </div>
    </div>
  );
}

/** Transport mode (EXPRESS / SURFACE) + direction. */
export function TransportCell({ shipment }: { shipment: PickupRead }) {
  const isAir = shipment.service_type === ServiceType.AIR;
  const Icon = isAir ? Plane : Truck;
  const isReverse = shipment.shipment_type === ShipmentType.REVERSE;
  return (
    <div className="flex flex-col gap-0.5 text-xs">
      <span className="text-slate-500">{isReverse ? "Reverse" : "Forward"}</span>
      <span className="flex items-center gap-1.5 font-semibold text-slate-800">
        <Icon className="h-4 w-4" />
        {TRANSPORT_MODE_LABEL[shipment.service_type] ?? shipment.service_type}
      </span>
    </div>
  );
}

/** Payment mode (+ COD amount as sent by the API). */
export function PaymentModeCell({ shipment, flow }: { shipment: PickupRead; flow: ServiceFlow }) {
  const { label, codAmount } = getPaymentModeDisplay(shipment, flow);
  return (
    <div className="flex flex-col text-sm">
      <span className="font-medium text-slate-800">{label}</span>
      {codAmount !== null && flow === ServiceFlow.B2B && (
        <span className="text-xs text-slate-500">COD ₹{codAmount.toLocaleString("en-IN")}</span>
      )}
      {codAmount !== null && flow === ServiceFlow.B2C && (
        <span className="text-xs text-slate-500">₹{codAmount.toLocaleString("en-IN")}</span>
      )}
    </div>
  );
}

/** Status pill used in the mobile card list. */
export function OrderStatusText({ status }: { status: PickupStatus }) {
  return (
    <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
      {getShipmentStatusLabel(status)}
    </span>
  );
}

/** Sortable column header button. */
function _sortableHeader(label: string) {
  return function SortableHeader({
    column,
  }: {
    column: { toggleSorting: (desc?: boolean) => void; getIsSorted: () => false | "asc" | "desc" };
  }) {
    return (
      <Button
        variant="ghost"
        className="-ml-4 font-bold hover:bg-slate-100/50"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
      >
        {label}
        <ArrowUpDown className="ml-2 h-3.5 w-3.5 text-slate-400" />
      </Button>
    );
  };
}

/**
 * Builds the Orders grid columns for a flow.
 *
 * @param flow - Active flow (B2C parcels or B2B cargo).
 * @param permissions - What the user may do from a row.
 * @returns Column definitions (without the selection column).
 */
export function buildOrderColumns(
  flow: ServiceFlow,
  permissions: OrderRowPermissions
): ColumnDef<PickupRead>[] {
  const copy = ORDERS_FLOW_COPY[flow];
  return [
    {
      accessorKey: "tracking_id",
      header: _sortableHeader(`${copy.idNoun} & Order ID`),
      cell: ({ row }) => <OrderIdCell shipment={row.original} copy={copy} />,
    },
    {
      accessorKey: "created_at",
      header: _sortableHeader("Manifested date"),
      cell: ({ row }) => {
        const formatted = formatManifestedDate(row.original.created_at);
        if (!formatted) return <span className="text-xs text-slate-400">-</span>;
        return (
          <div className="flex flex-col text-sm">
            <span className="font-medium text-slate-800">{formatted.date}</span>
            <span className="text-xs text-slate-500">{formatted.time}</span>
          </div>
        );
      },
    },
    {
      id: "pickup_delivery",
      header: "Pickup & delivery",
      cell: ({ row }) => <PickupDeliveryCell shipment={row.original} />,
    },
    {
      id: "transport",
      header: "Transport & zone",
      cell: ({ row }) => <TransportCell shipment={row.original} />,
    },
    {
      id: "payment",
      header: "Payment mode",
      cell: ({ row }) => <PaymentModeCell shipment={row.original} flow={flow} />,
    },
    {
      id: "actions",
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <OrderRowActions shipment={row.original} copy={copy} permissions={permissions} />
      ),
    },
  ];
}

/**
 * Orders grid columns with the leading "Add to pickup" checkbox column.
 *
 * @param flow - Active flow.
 * @param permissions - What the user may do from a row.
 * @param selection - Controlled selection state, or null to omit the checkbox
 *   column (users who cannot book pickups).
 * @returns Column definitions in display order.
 */
export function buildOrderColumnsWithSelection(
  flow: ServiceFlow,
  permissions: OrderRowPermissions,
  selection: RowSelectionOptions<PickupRead> | null
): ColumnDef<PickupRead>[] {
  const columns = buildOrderColumns(flow, permissions);
  return selection ? [buildSelectionColumn(selection)].concat(columns) : columns;
}
