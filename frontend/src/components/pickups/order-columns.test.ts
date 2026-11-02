// frontend/src/components/pickups/order-columns.test.ts
import { ShipmentType, type PickupRead } from "@/api_client";
import { ServiceFlow } from "@/lib/workspace-flow";
import { describe, expect, it } from "vitest";
import { ORDERS_FLOW_COPY, buildInitiateReturnHref, formatManifestedDate } from "./order-columns";

const SHIPMENT = { id: "s-1", shipment_type: ShipmentType.FORWARD } as unknown as PickupRead;

describe("buildInitiateReturnHref (WP0: B2B reverse LRs off for the MVP)", () => {
  it("prefills B2C returns from the forward shipment", () => {
    expect(buildInitiateReturnHref(SHIPMENT, ORDERS_FLOW_COPY[ServiceFlow.B2C])).toBe(
      "/shipments/new/reverse?from_shipment_id=s-1",
    );
  });

  it("offers no return link for B2B", () => {
    expect(ORDERS_FLOW_COPY[ServiceFlow.B2B].reverseHref).toBeNull();
    expect(buildInitiateReturnHref(SHIPMENT, ORDERS_FLOW_COPY[ServiceFlow.B2B])).toBeNull();
  });
});

describe("formatManifestedDate (F-02: API timestamps are UTC, show IST)", () => {
  it("shifts a naive UTC timestamp to the IST calendar day and time", () => {
    // 22:28 UTC on 30 Oct is 03:58 IST on 31 Oct.
    expect(formatManifestedDate("2026-10-30T22:28:00")).toEqual({ date: "31 Oct, 2026", time: "3:58am" });
  });

  it("returns null for missing or invalid values", () => {
    expect(formatManifestedDate(null)).toBeNull();
    expect(formatManifestedDate("not-a-date")).toBeNull();
  });
});
