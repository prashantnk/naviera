// frontend/src/components/booking/use-quote-booking.ts
"use client";

/**
 * Shared quote → book state machine for the booking wizards.
 *
 * - `requestQuote` prices the exact booking inputs (A-03) and pre-selects a card.
 * - `book` sends the booking with an `Idempotency-Key` (A-17). The key is kept only
 *   when no response arrived (a plain retry then replays the first booking) and is
 *   renewed after any server answer, after a re-quote and when the card changes.
 * - A 409 PRICE_CHANGED opens the confirm dialog; confirming re-sends the same body
 *   with `expected_total = new_total` and a fresh key (DESIGN.md v4, Q7).
 *
 * Spring analogy: a small stateful service bean behind the wizard controller.
 */
import { ApiError, type PickupRead } from "@/api_client";
import { formatInr } from "@/components/shipments/shipment-money";
import { extractApiErrorMessage } from "@/lib/utils";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import {
  createShipmentIdempotent,
  fetchQuotes,
  newBookingKey,
  parsePriceChanged,
  type BookingPayload,
  type PriceChangedDetail,
  type QuoteOption,
  type QuoteRequest,
  type QuoteResponse,
  type ServiceOption,
} from "./booking-api";
import { defaultSelection, findSelectedOption } from "./quote-step";

export interface UseQuoteBookingOptions {
  /** Called after a successful booking (e.g. to clear the draft and navigate). */
  onBooked: (created: PickupRead) => void;
  /** Toast text when the booking fails for an unexplained reason. */
  bookingFailedMessage: string;
}

export interface QuoteBookingState {
  quote: QuoteResponse | null;
  isQuoting: boolean;
  selectedOption: ServiceOption | null;
  selectOption: (option: ServiceOption) => void;
  /** Prices the inputs; resolves null (after a toast) when quoting failed. */
  requestQuote: (request: QuoteRequest) => Promise<QuoteResponse | null>;
  /** Books the selected card; `buildPayload` maps it to the booking body. */
  book: (buildPayload: (option: QuoteOption) => BookingPayload) => Promise<void>;
  isSubmitting: boolean;
  priceChange: PriceChangedDetail | null;
  confirmPriceChange: () => Promise<void>;
  cancelPriceChange: () => void;
}

/**
 * Whether a failure got no HTTP answer (offline, timeout), so a retry with the same
 * Idempotency-Key is safe and replays the first booking if it did commit.
 *
 * @param error - Error thrown by the booking call.
 * @returns True for transport failures.
 */
export function isNoResponseFailure(error: unknown): boolean {
  return !(error instanceof ApiError);
}

/**
 * Builds the success toast with the booked total read from the API response.
 *
 * @param created - The created shipment.
 * @returns Toast text.
 */
export function bookedToastMessage(created: PickupRead): string {
  const total = created.payment_details?.total_logistics_cost;
  return total == null
    ? "Shipment booked successfully!"
    : `Shipment booked. ${formatInr(total)} charged to your wallet.`;
}

export function useQuoteBooking({ onBooked, bookingFailedMessage }: UseQuoteBookingOptions): QuoteBookingState {
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [isQuoting, setIsQuoting] = useState(false);
  const [selectedOption, setSelectedOption] = useState<ServiceOption | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [priceChange, setPriceChange] = useState<PriceChangedDetail | null>(null);
  const keyRef = useRef<string | null>(null);
  const lastPayloadRef = useRef<BookingPayload | null>(null);

  const selectOption = useCallback((option: ServiceOption) => {
    keyRef.current = null;
    setSelectedOption(option);
  }, []);

  const requestQuote = useCallback(async (request: QuoteRequest) => {
    keyRef.current = null;
    setIsQuoting(true);
    setQuote(null);
    try {
      const response = await fetchQuotes(request);
      setQuote(response);
      setSelectedOption((previous) => defaultSelection(response, previous));
      return response;
    } catch (error) {
      toast.error(extractApiErrorMessage(error, "Couldn't fetch prices. Please try again."));
      return null;
    } finally {
      setIsQuoting(false);
    }
  }, []);

  const send = useCallback(
    async (payload: BookingPayload) => {
      keyRef.current ??= newBookingKey();
      lastPayloadRef.current = payload;
      setIsSubmitting(true);
      try {
        const created = await createShipmentIdempotent(payload, keyRef.current);
        toast.success(bookedToastMessage(created));
        onBooked(created);
      } catch (error) {
        if (!isNoResponseFailure(error)) keyRef.current = null;
        const change = parsePriceChanged(error);
        if (change) {
          setPriceChange(change);
          return;
        }
        toast.error(extractApiErrorMessage(error, bookingFailedMessage));
      } finally {
        setIsSubmitting(false);
      }
    },
    [onBooked, bookingFailedMessage],
  );

  const book = useCallback(
    async (buildPayload: (option: QuoteOption) => BookingPayload) => {
      const option = findSelectedOption(quote, selectedOption);
      if (!option) {
        toast.error("Please choose an available service first.");
        return;
      }
      await send(buildPayload(option));
    },
    [quote, selectedOption, send],
  );

  const confirmPriceChange = useCallback(async () => {
    const change = priceChange;
    const payload = lastPayloadRef.current;
    if (!change || !payload) return;
    keyRef.current = null;
    await send({ ...payload, expected_total: change.new_total });
    // Close unless the re-send hit yet another price change (then the new one shows).
    setPriceChange((current) => (current === change ? null : current));
  }, [priceChange, send]);

  const cancelPriceChange = useCallback(() => setPriceChange(null), []);

  return {
    quote,
    isQuoting,
    selectedOption,
    selectOption,
    requestQuote,
    book,
    isSubmitting,
    priceChange,
    confirmPriceChange,
    cancelPriceChange,
  };
}
