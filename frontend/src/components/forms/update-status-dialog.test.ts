// frontend/src/components/forms/update-status-dialog.test.ts
import { describe, expect, it } from "vitest";

import { PickupStatus } from "@/api_client";

import { buildStatusSelectOptions } from "./update-status-dialog";

const values = (current: PickupStatus, allowed: PickupStatus[], isAdmin = true) =>
  buildStatusSelectOptions(current, allowed, isAdmin).map((o) => o.value);

describe("E-11 status options come from the server", () => {
  it("offers exactly the current status plus allowed_next_statuses", () => {
    expect(
      new Set(values(PickupStatus.OUT_FOR_DELIVERY, [PickupStatus.COMPLETED, PickupStatus.EXCEPTION])),
    ).toEqual(new Set([PickupStatus.OUT_FOR_DELIVERY, PickupStatus.COMPLETED, PickupStatus.EXCEPTION]));
  });

  it("a terminal status offers nothing else", () => {
    expect(values(PickupStatus.RTO_DELIVERED, [])).toEqual([PickupStatus.RTO_DELIVERED]);
  });

  it("never invents a move the server did not list", () => {
    expect(values(PickupStatus.RTO_IN_TRANSIT, [PickupStatus.RTO_DELIVERED])).not.toContain(PickupStatus.COMPLETED);
  });

  it("hides Lost and manual RTO from non-admin staff (server answers 403)", () => {
    const allowed = [PickupStatus.COMPLETED, PickupStatus.RTO_INITIATED, PickupStatus.LOST];
    expect(new Set(values(PickupStatus.OUT_FOR_DELIVERY, allowed, false))).toEqual(
      new Set([PickupStatus.OUT_FOR_DELIVERY, PickupStatus.COMPLETED]),
    );
    expect(values(PickupStatus.OUT_FOR_DELIVERY, allowed, true)).toContain(PickupStatus.LOST);
  });
});
