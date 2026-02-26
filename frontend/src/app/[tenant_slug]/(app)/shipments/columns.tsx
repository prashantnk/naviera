// src/app/[tenant_slug]/(app)/shipments/columns.tsx
"use client";

import { PickupRead, PickupStatus } from "@/api_client"; // STRICT TYPES!
import { Badge } from "@/components/ui/badge";
import { ColumnDef } from "@tanstack/react-table";

// Notice we pass PickupRead into the ColumnDef
export const columns: ColumnDef<PickupRead>[] = [
    {
        accessorKey: "tracking_id",
        header: "Tracking ID",
        cell: ({ row }) => {
            // Safely handle the string | null scenario!
            const trackingId = row.getValue("tracking_id") as string | null;
            return (
                <span className="font-mono font-medium">
                    {trackingId ? trackingId : <span className="text-slate-400">Pending</span>}
                </span>
            );
        },
    },
    {
        accessorKey: "requested_pickup_date",
        header: "Pickup Date",
    },
    {
        accessorFn: (row) => row.pickup_address?.city,
        id: "origin",
        header: "Origin",
    },
    {
        accessorFn: (row) => row.delivery_address?.city,
        id: "destination",
        header: "Destination",
    },
    {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
            const status = row.getValue("status") as PickupStatus;

            let variant: "default" | "secondary" | "destructive" | "outline" = "secondary";

            if (status === PickupStatus.COMPLETED) variant = "default";
            if (status === PickupStatus.CANCELLED || status === PickupStatus.RTO_INITIATED) variant = "destructive";
            if (status === PickupStatus.IN_TRANSIT) variant = "default";

            return <Badge variant={variant}>{status.replace("_", " ")}</Badge>;
        },
    },
];