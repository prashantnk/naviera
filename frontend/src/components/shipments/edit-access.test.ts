// frontend/src/components/shipments/edit-access.test.ts
import { PickupStatus } from "@/api_client";
import { describe, expect, it } from "vitest";

import { NON_EDITABLE_STATUSES, canOpenShipmentEdit } from "./edit-access";

const BOOKER = { canOperate: false, canBook: true };
const OPERATOR = { canOperate: true, canBook: false };
const READ_ONLY = { canOperate: false, canBook: false };

describe("canOpenShipmentEdit", () => {
  it.each([
    PickupStatus.RTO_INITIATED,
    PickupStatus.RTO_IN_TRANSIT,
    PickupStatus.RTO_DELIVERED,
    PickupStatus.LOST,
    PickupStatus.COMPLETED,
    PickupStatus.CANCELLED,
  ])("hides Edit from bookers on final state %s", (status) => {
    expect(NON_EDITABLE_STATUSES.has(status)).toBe(true);
    expect(canOpenShipmentEdit(BOOKER, status)).toBe(false);
  });

  it.each([
    PickupStatus.OPEN,
    PickupStatus.ASSIGNED,
    PickupStatus.IN_TRANSIT,
    PickupStatus.OUT_FOR_DELIVERY,
  ])("shows Edit to bookers on live state %s", (status) => {
    expect(canOpenShipmentEdit(BOOKER, status)).toBe(true);
  });

  it("always shows Edit to operators and never to read-only users", () => {
    for (const status of Object.values(PickupStatus)) {
      expect(canOpenShipmentEdit(OPERATOR, status)).toBe(true);
      expect(canOpenShipmentEdit(READ_ONLY, status)).toBe(false);
    }
  });
});
