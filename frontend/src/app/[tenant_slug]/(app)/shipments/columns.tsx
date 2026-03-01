// frontend/src/app/[tenant_slug]/(app)/shipments/columns.tsx
"use client";

import { PickupRead, PickupStatus } from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { ColumnDef } from "@tanstack/react-table";
import {
  ArrowRight,
  Box,
  Calendar,
  MessageSquare,
  Phone,
  Repeat,
  Truck,
  Zap,
} from "lucide-react";

// Robust status color mapper
const getStatusColor = (status: PickupStatus) => {
  switch (status) {
    case PickupStatus.DRAFT:
      return "bg-slate-100 text-slate-700 border-slate-200";
    case PickupStatus.OPEN:
      return "bg-sky-100 text-sky-700 border-sky-200";
    case PickupStatus.ASSIGNED:
      return "bg-indigo-100 text-indigo-700 border-indigo-200";
    case PickupStatus.IN_TRANSIT:
      return "bg-blue-100 text-blue-700 border-blue-200";
    case PickupStatus.COMPLETED:
      return "bg-emerald-100 text-emerald-700 border-emerald-200";
    case PickupStatus.CANCELLED:
      return "bg-rose-100 text-rose-700 border-rose-200";
    case PickupStatus.RTO_INITIATED:
      return "bg-amber-100 text-amber-700 border-amber-200";
    default:
      return "bg-slate-100 text-slate-700";
  }
};

export const columns: ColumnDef<PickupRead>[] = [
  {
    id: "identifiers",
    header: "Order / Tracking ID",
    cell: ({ row }) => {
      const refId = row.original.order_reference_id;
      const trackingId = row.original.tracking_id;

      return (
        <div className="flex flex-col">
          <span className="font-extrabold text-slate-900 text-sm tracking-tight">
            {refId}
          </span>
          <span className="text-[11px] text-slate-500 font-mono mt-0.5 bg-slate-100 w-fit px-1.5 rounded border border-slate-200">
            {trackingId || "PENDING"}
          </span>
        </div>
      );
    },
  },
  {
    id: "contact",
    header: "Sender Contact",
    cell: ({ row }) => {
      const name = row.original.pickup_address?.name || "Unknown";
      const phone = row.original.pickup_address?.phone || "N/A";

      return (
        <div className="flex flex-col">
          <span className="font-semibold text-slate-700 text-sm">{name}</span>
          <span className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
            <Phone className="h-3 w-3 text-slate-400" /> {phone}
          </span>
        </div>
      );
    },
  },
  {
    id: "logistics",
    header: "Service & Type",
    cell: ({ row }) => {
      const service = row.original.service_type;
      const type = row.original.shipment_type;
      const isExpress = service === "EXPRESS";
      const isReverse = type === "REVERSE";

      return (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-600">
            {isExpress ? (
              <Zap className="h-3.5 w-3.5 text-amber-500" />
            ) : (
              <Truck className="h-3.5 w-3.5 text-slate-400" />
            )}
            {service}
          </div>
          <div
            className={cn(
              "flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider",
              isReverse ? "text-rose-500" : "text-slate-500"
            )}
          >
            {isReverse ? (
              <Repeat className="h-3.5 w-3.5" />
            ) : (
              <Box className="h-3.5 w-3.5" />
            )}
            {type}
          </div>
        </div>
      );
    },
  },
  {
    id: "route",
    header: "Route",
    cell: ({ row }) => {
      const origin = row.original.pickup_address?.city || "Unknown";
      const dest = row.original.delivery_address?.city || "Unknown";
      return (
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <span>{origin}</span>
          <ArrowRight className="h-3.5 w-3.5 text-slate-300 shrink-0" />
          <span>{dest}</span>
        </div>
      );
    },
  },
  {
    id: "status_date",
    header: "Status & Date",
    cell: ({ row }) => {
      const status = row.original.status;
      // The Date requested for the pickup
      const dateStr = row.original.requested_pickup_date;
      // Handle edge cases if date string comes in weirdly formatted
      const formattedDate = dateStr
        ? new Date(dateStr).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })
        : "TBD";

      return (
        <div className="flex flex-col items-start gap-1.5">
          <Badge
            variant="outline"
            className={cn(
              "px-2.5 py-0.5 shadow-none text-[10px] uppercase font-bold tracking-wider rounded-md",
              getStatusColor(status)
            )}
          >
            {status.replace("_", " ")}
          </Badge>
          <span className="text-xs text-slate-500 flex items-center gap-1 font-medium">
            <Calendar className="h-3 w-3 text-slate-400" /> {formattedDate}
          </span>
        </div>
      );
    },
  },
  {
    id: "comment",
    header: "Latest Note",
    cell: ({ row }) => {
      const comment = row.original.latest_status_comment;

      if (!comment) {
        return <span className="text-xs text-slate-400 italic">No notes</span>;
      }

      return (
        <div className="flex items-start gap-1.5 max-w-[200px]">
          <MessageSquare className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
          <span
            className="text-xs text-slate-600 line-clamp-2 leading-relaxed"
            title={comment}
          >
            {comment}
          </span>
        </div>
      );
    },
  },
];
