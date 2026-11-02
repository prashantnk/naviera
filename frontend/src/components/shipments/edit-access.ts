// frontend/src/components/shipments/edit-access.ts
/**
 * Decides whether to SHOW the "Edit" entry on a shipment detail page (plan B9).
 *
 * This is visibility only. The backend is the gatekeeper: it returns the H-8 / H-12 / B9
 * refusals per field in the re-price preview, and the edit page shows them verbatim.
 * Staff can open the editor while the shipment is live; merchants can open it for their
 * own orders until the order reaches a final state (Delhivery One `update-forward-order`).
 */
import { PickupStatus } from "@/api_client";
import type { UserCapabilities } from "@/components/auth/capabilities";

/**
 * Final states for a booker: nothing about the order can change any more. Includes the
 * whole RTO leg and Lost (audit D-02 / A1-23), which the backend refuses to re-price.
 */
export const NON_EDITABLE_STATUSES: ReadonlySet<PickupStatus> = new Set([
  PickupStatus.COMPLETED,
  PickupStatus.CANCELLED,
  PickupStatus.RTO_INITIATED,
  PickupStatus.RTO_IN_TRANSIT,
  PickupStatus.RTO_DELIVERED,
  PickupStatus.LOST,
  PickupStatus.QC_FAILED,
  PickupStatus.REJECTED_AT_PICKUP,
]);

/**
 * Whether the current user should see the Edit button for a shipment in `status`.
 *
 * @param capabilities - Resolved UI capabilities of the user.
 * @param status - Current shipment status.
 * @returns True for staff operators always, and for bookers while the order is not final.
 */
export function canOpenShipmentEdit(
  capabilities: Pick<UserCapabilities, "canOperate" | "canBook">,
  status: PickupStatus,
): boolean {
  if (capabilities.canOperate) return true;
  return capabilities.canBook && !NON_EDITABLE_STATUSES.has(status);
}
