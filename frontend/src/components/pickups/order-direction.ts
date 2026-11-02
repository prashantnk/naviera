// frontend/src/components/pickups/order-direction.ts
import { ShipmentType } from "@/api_client";
import { B2B_REVERSE_BOOKING_ENABLED } from "@/lib/mvp-scope";
import { ServiceFlow } from "@/lib/workspace-flow";
import { ArrowDownLeft, ArrowUpRight, type LucideIcon } from "lucide-react";

/** Sentinel value of the "All" direction tab / filter. */
export const ALL_DIRECTIONS = "ALL";

/** One tab of the Orders page direction switcher (All / Forward / Reverse). */
export interface DirectionTab {
  value: typeof ALL_DIRECTIONS | ShipmentType;
  label: string;
  icon: LucideIcon | null;
}

/** Reverse tab label per flow: B2C returns are DTO parcels, B2B returns are reverse LRs. */
const REVERSE_TAB_LABEL: Readonly<Record<ServiceFlow, string>> = {
  [ServiceFlow.B2C]: "Reverse (DTO) Returns",
  [ServiceFlow.B2B]: "Reverse LRs",
};

/**
 * Whether the Orders page offers a Forward/Reverse direction filter for a flow.
 *
 * B2B reverse LRs are switched off for the MVP (WP0), so a B2B "Reverse" tab would only ever
 * be empty and suggest a feature that does not exist; the B2B page then shows no direction
 * switcher at all (every B2B LR is forward).
 *
 * @param flow - Orders page flow.
 * @param b2bReverseEnabled - MVP switch (defaults to `B2B_REVERSE_BOOKING_ENABLED`).
 * @returns True when the direction tabs and the "Shipment type" filter should render.
 */
export function showsDirectionFilter(
  flow: ServiceFlow,
  b2bReverseEnabled: boolean = B2B_REVERSE_BOOKING_ENABLED,
): boolean {
  return flow === ServiceFlow.B2C || b2bReverseEnabled;
}

/**
 * Direction tabs of the Orders page for a flow (empty when the flow has no reverse orders).
 *
 * @param flow - Orders page flow.
 * @param b2bReverseEnabled - MVP switch (defaults to `B2B_REVERSE_BOOKING_ENABLED`).
 * @returns The tabs in display order.
 */
export function directionTabsFor(
  flow: ServiceFlow,
  b2bReverseEnabled: boolean = B2B_REVERSE_BOOKING_ENABLED,
): DirectionTab[] {
  if (!showsDirectionFilter(flow, b2bReverseEnabled)) return [];
  return [
    { value: ALL_DIRECTIONS, label: "All Orders", icon: null },
    { value: ShipmentType.FORWARD, label: "Forward Orders", icon: ArrowUpRight },
    { value: ShipmentType.REVERSE, label: REVERSE_TAB_LABEL[flow], icon: ArrowDownLeft },
  ];
}
