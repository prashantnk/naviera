// frontend/src/components/booking/use-quote-booking.test.ts
import type { PickupRead } from "@/api_client";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ServiceOption,
  createShipmentIdempotent,
  fetchQuotes,
  type BookingPayload,
  type QuoteOption,
  type QuoteResponse,
} from "./booking-api";
import { useQuoteBooking } from "./use-quote-booking";

vi.mock("./booking-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./booking-api")>()),
  fetchQuotes: vi.fn(),
  createShipmentIdempotent: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const OPTION: QuoteOption = {
  service_option: ServiceOption.DELHIVERY_SURFACE,
  serviceable: true,
  total_amount: 159.3,
  freight_amount: 135,
  cod_fee: 0,
  tax_amount: 24.3,
  chargeable_weight_kg: 2,
  transit_days: 3,
  expected_delivery_date: "2026-11-02",
  sell_lines: [],
  door_collectible_amount: 0,
  cod_remittance_amount: 0,
  priced_from_cache: false,
};

const QUOTE: QuoteResponse = {
  shipment_total_value: 1000,
  eway_bill_required: false,
  eway_bill_threshold: 50000,
  cod_available: true,
  heavy_weight_warning: false,
  heavy_weight_threshold_kg: 100,
  options: [OPTION],
};

describe("useQuoteBooking double-submit guard", () => {
  beforeEach(() => {
    vi.mocked(fetchQuotes).mockReset().mockResolvedValue(QUOTE);
    vi.mocked(createShipmentIdempotent).mockReset();
  });

  it("sends one booking for a fast double click and re-enables after", async () => {
    let resolveBooking!: (created: PickupRead) => void;
    vi.mocked(createShipmentIdempotent).mockReturnValue(
      new Promise<PickupRead>((resolve) => {
        resolveBooking = resolve;
      }) as ReturnType<typeof createShipmentIdempotent>,
    );
    const onBooked = vi.fn();
    const { result } = renderHook(() =>
      useQuoteBooking({ onBooked, bookingFailedMessage: "Booking failed" }),
    );
    await act(async () => {
      await result.current.requestQuote({} as Parameters<typeof fetchQuotes>[0]);
    });

    const buildPayload = () => ({}) as BookingPayload;
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.book(buildPayload);
      second = result.current.book(buildPayload);
    });

    expect(createShipmentIdempotent).toHaveBeenCalledTimes(1);
    expect(result.current.isSubmitting).toBe(true);

    await act(async () => {
      resolveBooking({ id: "s-1" } as PickupRead);
      await Promise.all([first, second]);
    });
    expect(onBooked).toHaveBeenCalledTimes(1);
    expect(result.current.isSubmitting).toBe(false);
  });
});
