import { ShipmentType } from "@/api_client";
import { ServiceFlow } from "@/lib/workspace-flow";
import { describe, expect, it } from "vitest";

import { ALL_DIRECTIONS, directionTabsFor, showsDirectionFilter } from "./order-direction";

describe("order direction tabs (WP0: B2B reverse off)", () => {
  it("B2C always offers All / Forward / Reverse (DTO) Returns", () => {
    expect(directionTabsFor(ServiceFlow.B2C, false).map((tab) => tab.label)).toEqual([
      "All Orders",
      "Forward Orders",
      "Reverse (DTO) Returns",
    ]);
    expect(showsDirectionFilter(ServiceFlow.B2C, false)).toBe(true);
  });

  it("B2B shows no direction switcher while reverse LRs are switched off", () => {
    expect(directionTabsFor(ServiceFlow.B2B, false)).toEqual([]);
    expect(showsDirectionFilter(ServiceFlow.B2B, false)).toBe(false);
  });

  it("B2B gets a 'Reverse LRs' tab (not the B2C DTO wording) once reverse is enabled", () => {
    const tabs = directionTabsFor(ServiceFlow.B2B, true);
    expect(tabs.map((tab) => tab.value)).toEqual([
      ALL_DIRECTIONS,
      ShipmentType.FORWARD,
      ShipmentType.REVERSE,
    ]);
    expect(tabs[2].label).toBe("Reverse LRs");
  });

  it("defaults to the shipped MVP switch (B2B reverse off)", () => {
    expect(directionTabsFor(ServiceFlow.B2B)).toEqual([]);
  });
});
