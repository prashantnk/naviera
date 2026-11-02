// frontend/src/components/pickups/use-shipment-status-query.test.ts
import { PickupStatus } from "@/api_client";
import { describe, expect, it } from "vitest";

import { parseShipmentStatusParam } from "./use-shipment-status-query";

describe("parseShipmentStatusParam", () => {
  it("returns no statuses when the param is absent", () => {
    expect(parseShipmentStatusParam(null)).toEqual([]);
    expect(parseShipmentStatusParam("")).toEqual([]);
  });

  it("parses single and comma-separated enum values", () => {
    expect(parseShipmentStatusParam("OPEN")).toEqual([PickupStatus.OPEN]);
    expect(parseShipmentStatusParam("IN_TRANSIT, exception")).toEqual([
      PickupStatus.IN_TRANSIT,
      PickupStatus.EXCEPTION,
    ]);
  });

  it("drops unknown and duplicate values", () => {
    expect(parseShipmentStatusParam("OPEN,BOGUS,OPEN,ASSIGNED")).toEqual([
      PickupStatus.OPEN,
      PickupStatus.ASSIGNED,
    ]);
  });
});
