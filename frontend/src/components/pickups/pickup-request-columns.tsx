// frontend/src/components/pickups/pickup-request-columns.tsx
"use client";

/**
 * TanStack column definitions for the Pickup Requests table, matching the
 * Delhivery One layout exactly: [select] · Pickup ID · Pickup date & slot ·
 * Pickup location · Status · Action.
 */
import { ManifestResponse } from "@/api_client";
import type { ColumnDef } from "@tanstack/react-table";

import {
  PickupDateSlot,
  PickupIdLink,
  PickupLocationCell,
  PickupRowActions,
  PickupRowContext,
  PickupStatusCell,
} from "./pickup-row-parts";
import { buildSelectionColumn, RowSelectionOptions } from "./selection-column";

/**
 * Builds the Pickup Requests columns.
 *
 * @param context - Flow, role, action handlers and the in-flight row id.
 * @param selection - Controlled row selection (Delhivery shows a checkbox column).
 * @returns Column definitions for `DataTable`.
 */
export function getPickupRequestColumns(
  context: PickupRowContext,
  selection: RowSelectionOptions<ManifestResponse>
): ColumnDef<ManifestResponse>[] {
  const dataColumns: ColumnDef<ManifestResponse>[] = [
    {
      id: "pickup_id",
      header: "Pickup ID",
      cell: ({ row }) => <PickupIdLink manifest={row.original} />,
    },
    {
      id: "date_slot",
      header: "Pickup date & slot",
      cell: ({ row }) => <PickupDateSlot manifest={row.original} />,
    },
    {
      id: "location",
      header: "Pickup location",
      cell: ({ row }) => <PickupLocationCell manifest={row.original} />,
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) => <PickupStatusCell manifest={row.original} flow={context.flow} />,
    },
    {
      id: "actions",
      header: "Action",
      cell: ({ row }) => <PickupRowActions manifest={row.original} context={context} />,
    },
  ];
  return [buildSelectionColumn(selection)].concat(dataColumns);
}
