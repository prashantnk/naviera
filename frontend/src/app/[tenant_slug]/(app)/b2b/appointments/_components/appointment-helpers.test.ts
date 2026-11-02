// frontend/src/app/[tenant_slug]/(app)/b2b/appointments/_components/appointment-helpers.test.ts
import { PickupTimeSlot } from "@/api_client";
import { toIstDateTimeLocalValue, toIstIsoString } from "@/lib/utils";
import { describe, expect, it } from "vitest";

import {
  formatAppointmentDate,
  isoToDateAndSlot,
  PoState,
  resolvePoState,
  slotToIsoWindow,
  validateBookAppointment,
} from "./appointment-helpers";

describe("resolvePoState", () => {
  it("prefers PO missing over expired", () => {
    expect(resolvePoState({ po_missing: true, po_expired: true })).toBe(PoState.MISSING);
  });

  it("flags expired and valid POs", () => {
    expect(resolvePoState({ po_missing: false, po_expired: true })).toBe(PoState.EXPIRED);
    expect(resolvePoState({ po_missing: false, po_expired: false })).toBe(PoState.VALID);
  });
});

describe("slot conversions", () => {
  it("round-trips a local date + slot through ISO in IST (+05:30, D-09)", () => {
    const window = slotToIsoWindow("2026-10-22", PickupTimeSlot._10_00_14_00);
    expect(window.appointment_start).toBe("2026-10-22T04:30:00.000Z");
    expect(window.appointment_end).toBe("2026-10-22T08:30:00.000Z");
    expect(new Date(window.appointment_end).getTime() - new Date(window.appointment_start).getTime()).toBe(
      4 * 60 * 60 * 1000
    );
    expect(isoToDateAndSlot(window.appointment_start)).toEqual({
      date: "2026-10-22",
      slot: PickupTimeSlot._10_00_14_00,
    });
  });

  it("converts datetime-local IST inputs to UTC ISO and back without 5.5h drift", () => {
    const iso = toIstIsoString("2026-11-15T10:00");
    expect(iso).toBe("2026-11-15T04:30:00.000Z");
    expect(toIstDateTimeLocalValue(iso)).toBe("2026-11-15T10:00");
  });

  it("returns nulls for a missing or unknown start", () => {
    expect(isoToDateAndSlot(null)).toEqual({ date: null, slot: null });
    expect(isoToDateAndSlot("not-a-date")).toEqual({ date: null, slot: null });
  });
});

describe("formatAppointmentDate", () => {
  it("formats API dates and rejects junk", () => {
    expect(formatAppointmentDate("2026-10-22")).toBe("22 Oct 2026");
    expect(formatAppointmentDate("2026-10-22", true)).toBe("22 Oct");
    expect(formatAppointmentDate(null)).toBeNull();
    expect(formatAppointmentDate("junk")).toBeNull();
  });
});

describe("validateBookAppointment", () => {
  it("requires all four fields like Delhivery", () => {
    expect(validateBookAppointment({ poNumber: " ", poExpiry: "", date: "", slot: "" })).toEqual({
      poNumber: "PO number is required",
      poExpiry: "PO expiry date is required",
      date: "Appointment date is required",
      slot: "Appointment time is required",
    });
    expect(
      validateBookAppointment({
        poNumber: "PO1",
        poExpiry: "2026-11-01",
        date: "2026-10-22",
        slot: PickupTimeSlot._10_00_14_00,
      })
    ).toEqual({});
  });

  it("rejects more than 5 comma-separated PO numbers and PO expiry before appointment date", () => {
    expect(
      validateBookAppointment({
        poNumber: "PO1, PO2, PO3, PO4, PO5, PO6",
        poExpiry: "2026-10-20",
        date: "2026-10-22",
        slot: PickupTimeSlot._10_00_14_00,
      })
    ).toEqual({
      poNumber: "Maximum 5 comma-separated PO numbers are allowed",
      poExpiry: "PO expiry date cannot be earlier than the appointment date",
    });
  });
});
