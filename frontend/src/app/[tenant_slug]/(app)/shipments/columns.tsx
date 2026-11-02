// frontend/src/app/[tenant_slug]/(app)/shipments/columns.tsx
"use client";

/**
 * B2C Orders grid columns. The Delhivery-style columns are shared with B2B in
 * `components/pickups/order-columns.tsx`; this module keeps the route-local
 * entry point.
 */
import type { PickupRead } from "@/api_client";
import { buildOrderColumnsWithSelection } from "@/components/pickups/order-columns";
import type { RowSelectionOptions } from "@/components/pickups/selection-column";
import { ServiceFlow } from "@/lib/workspace-flow";
import type { ColumnDef } from "@tanstack/react-table";

/**
 * B2C order columns with the leading "Add to pickup" checkbox.
 *
 * @param selection - Controlled selection state owned by the Orders page.
 * @param canBook - Whether the user may add orders to pickups / start returns.
 * @returns Selection column followed by the standard columns.
 */
export function getShipmentColumnsWithSelection(
  selection: RowSelectionOptions<PickupRead>,
  canBook = true
): ColumnDef<PickupRead>[] {
  return buildOrderColumnsWithSelection(ServiceFlow.B2C, { canBook }, selection);
}
