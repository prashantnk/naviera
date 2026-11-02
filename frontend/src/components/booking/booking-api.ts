// frontend/src/components/booking/booking-api.ts
/**
 * Facade over the pricing-redesign booking endpoints (DESIGN.md v4, API_CONTRACT.md):
 *   POST /api/v1/quotes               option cards (prices computed by the backend)
 *   POST /api/v1/shipments/valuation  goods total + e-way bill rule (D-06)
 *   POST /api/v1/shipments            booking with a required Idempotency-Key (A-17)
 *
 * Booking pages import these helpers instead of the generated services so the raw
 * `Idempotency-Key` header (not in the OpenAPI spec) and the 409 PRICE_CHANGED body
 * are handled in one place. Types are the generated ones, re-exported.
 * All money numbers pass through exactly as the backend sent them (Zero Frontend Math).
 *
 * Spring analogy: a `@Component` facade around a Feign client.
 */
import {
  ApiError,
  OpenAPI,
  QuoteUnavailableCode,
  QuotesService,
  ServiceOption,
  ShipmentsService,
  type PickupCreate,
  type PickupRead,
  type QuoteOption,
  type QuoteRequest,
  type QuoteResponse,
  type SellLine,
  type ServiceFlow,
  type ValuationResponse,
} from "@/api_client";
import { request as __request } from "@/api_client/core/request";

export { ServiceOption };

export type { QuoteOption, QuoteRequest, QuoteResponse, SellLine };
export { QuoteUnavailableCode };

/** Goods valuation computed by the backend (D-06). */
export type ShipmentValuation = ValuationResponse;

/** Booking payload: the generated `PickupCreate` with the redesign fields required. */
export type BookingPayload = Omit<PickupCreate, "service_flow" | "service_option" | "expected_total"> & {
  service_flow: ServiceFlow;
  service_option: ServiceOption;
  expected_total: number;
};

/** 409 body when the fresh price at "Book" differs from the price the user saw. */
export interface PriceChangedDetail {
  code: typeof PRICE_CHANGED_CODE;
  message: string;
  expected_total: number;
  new_total: number;
  service_option: ServiceOption;
}

export const PRICE_CHANGED_CODE = "PRICE_CHANGED";
const CONFLICT_STATUS = 409;
const IDEMPOTENCY_HEADER = "Idempotency-Key";

/**
 * Fetches the option cards for the given booking inputs.
 *
 * @param payload - Exactly the inputs the booking will send.
 * @returns Shared facts and one card per service option.
 */
export function fetchQuotes(payload: QuoteRequest): Promise<QuoteResponse> {
  return QuotesService.getQuotes(payload);
}

/**
 * Asks the backend for the goods total and whether an e-way bill is required.
 *
 * @param shipmentValue - Net goods value typed by the user.
 * @param shipmentTaxValue - Goods tax typed by the user.
 * @returns The backend-computed valuation.
 */
export function fetchShipmentValuation(
  shipmentValue: number,
  shipmentTaxValue: number,
): Promise<ShipmentValuation> {
  return ShipmentsService.shipmentValuation({
    shipment_value: shipmentValue,
    shipment_tax_value: shipmentTaxValue,
  });
}

/**
 * Books a shipment with an `Idempotency-Key`, so a retry after a dropped response
 * replays the first booking instead of creating a second AWB and debit (A-17).
 *
 * @param payload - Booking body (same inputs as the quote).
 * @param idempotencyKey - One key per booking attempt; reuse it on a plain retry.
 * @returns The created shipment.
 */
export function createShipmentIdempotent(
  payload: BookingPayload,
  idempotencyKey: string,
): Promise<PickupRead> {
  return __request(OpenAPI, {
    method: "POST",
    url: "/api/v1/shipments",
    headers: { [IDEMPOTENCY_HEADER]: idempotencyKey },
    body: payload,
    mediaType: "application/json",
    errors: { 422: "Validation Error" },
  }) as unknown as Promise<PickupRead>;
}

/**
 * Creates a fresh Idempotency-Key for one booking attempt.
 *
 * @returns A random UUID string.
 */
export function newBookingKey(): string {
  return crypto.randomUUID();
}

/**
 * Extracts the PRICE_CHANGED detail from a failed booking, if that is the cause.
 *
 * @param error - Error thrown by the booking call.
 * @returns The 409 detail, or null for any other failure.
 */
export function parsePriceChanged(error: unknown): PriceChangedDetail | null {
  if (!(error instanceof ApiError) || error.status !== CONFLICT_STATUS) return null;
  const detail = (error.body as { detail?: unknown } | undefined)?.detail;
  if (!detail || typeof detail !== "object") return null;
  const candidate = detail as Partial<PriceChangedDetail>;
  if (candidate.code !== PRICE_CHANGED_CODE || typeof candidate.new_total !== "number") return null;
  return candidate as PriceChangedDetail;
}
