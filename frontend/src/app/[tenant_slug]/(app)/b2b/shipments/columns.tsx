// frontend/src/app/[tenant_slug]/(app)/b2b/shipments/columns.tsx
"use client";

/**
 * B2B Orders grid columns. The Delhivery-style columns are shared with B2C in
 * `components/pickups/order-columns.tsx`; this module keeps the route-local
 * entry point.
 */
import type { PickupRead } from "@/api_client";
import { buildOrderColumnsWithSelection } from "@/components/pickups/order-columns";
import type { RowSelectionOptions } from "@/components/pickups/selection-column";
import { ServiceFlow } from "@/lib/workspace-flow";
import type { ColumnDef } from "@tanstack/react-table";

/**
 * B2B order columns with the leading "Add to pickup" checkbox.
 *
 * @param selection - Controlled selection state owned by the B2B Orders page.
 * @param canBook - Whether the user may add LRs to pickups / start returns.
 * @returns Selection column followed by the standard columns.
 */
export function getShipmentColumnsWithSelection(
  selection: RowSelectionOptions<PickupRead>,
  canBook = true
): ColumnDef<PickupRead>[] {
  return buildOrderColumnsWithSelection(ServiceFlow.B2B, { canBook }, selection);
}
