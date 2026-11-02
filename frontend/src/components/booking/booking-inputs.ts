// frontend/src/components/booking/booking-inputs.ts
/**
 * One source for the money inputs a wizard sends, so the quote and the booking are
 * priced on exactly the same values (audit A-03) and the typed COD amount is the
 * goods COD, never replaced by the order value (A-01).
 */
import type { FreightPaymentMode, PackageCreate, ServiceFlow, ShipmentType } from "@/api_client";
import type { QuoteRequest } from "./booking-api";
import { toValuationInput } from "./use-shipment-valuation";

/** The payment fields every booking form collects. */
export interface PaymentFormValues {
  freight_payment_mode: FreightPaymentMode;
  is_cod?: boolean;
  cod_amount?: number | string;
  shipment_value?: number | string;
  shipment_tax_value?: number | string;
}

/** Money inputs shared verbatim by `QuoteRequest` and `payment_details`. */
export interface PaymentInputs {
  freight_payment_mode: FreightPaymentMode;
  is_cod: boolean;
  cod_amount: number;
  add_shipping_to_cod: boolean;
  shipment_value: number;
  shipment_tax_value: number;
}

/**
 * Normalises the form's payment fields (numbers may be "" while typing).
 *
 * @param values - Payment fields from the form.
 * @param addShippingToCod - The "add shipping charges to COD" tick.
 * @returns Inputs for both the quote and the booking.
 */
export function buildPaymentInputs(values: PaymentFormValues, addShippingToCod: boolean): PaymentInputs {
  const isCod = Boolean(values.is_cod);
  return {
    freight_payment_mode: values.freight_payment_mode,
    is_cod: isCod,
    cod_amount: isCod ? toValuationInput(values.cod_amount) : 0,
    add_shipping_to_cod: isCod && addShippingToCod,
    shipment_value: toValuationInput(values.shipment_value),
    shipment_tax_value: toValuationInput(values.shipment_tax_value),
  };
}

export interface QuoteRequestArgs {
  flow: ServiceFlow;
  shipmentType: ShipmentType;
  pickupPincode: string;
  deliveryPincode: string;
  packages: PackageCreate[];
  payment: PaymentInputs;
  isBlindPickup?: boolean;
  estimatedBoxCount?: number | null;
  doorDelivery?: boolean;
  /** B2B insurance: carrier's risk (Delhivery prices its risk charge on it). */
  isCarriersRisk?: boolean;
}

/**
 * Builds the `POST /api/v1/quotes` body from the same inputs the booking sends.
 *
 * @param args - Route, boxes and payment inputs.
 * @returns The quote request.
 */
export function buildQuoteRequest(args: QuoteRequestArgs): QuoteRequest {
  return {
    service_flow: args.flow,
    shipment_type: args.shipmentType,
    pickup_pincode: args.pickupPincode,
    delivery_pincode: args.deliveryPincode,
    packages: args.packages,
    is_blind_pickup: args.isBlindPickup ?? false,
    estimated_box_count: args.estimatedBoxCount ?? null,
    door_delivery: args.doorDelivery ?? false,
    is_carriers_risk: args.isCarriersRisk ?? false,
    ...args.payment,
  };
}
