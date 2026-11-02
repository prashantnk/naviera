// frontend/src/components/carrier/carrier-api.ts
/**
 * Thin typed adapter over the ops carrier-booking endpoints (API_CONTRACT §5):
 *   GET /api/v1/shipments/{id}/carrier-billing  (staff read)
 *   PUT /api/v1/shipments/{id}/carrier-billing  (owner / admin / operations write)
 *
 * Ops book the parcel on one.delhivery.com and paste the Delhivery AWB, charged weight
 * and charged amount here. The backend compares them with what the seller was billed and
 * returns the margin and `has_gap` / `gap_amount` / `gap_message`; this module never computes
 * money (Zero Frontend Math). Types come from the generated `src/api_client`.
 *
 * Delhivery One parity: the AWB shown on every order row and order detail page.
 *
 * Spring analogy: a `@Component` facade around a Feign client plus its DTOs.
 */
import {
  ApiError,
  ServiceOption,
  ShipmentsService,
  type CarrierBillingRead,
  type CarrierBillingUpdate,
} from "@/api_client";
import { SERVICE_OPTION_OPTIONS } from "@/lib/form-options";

export type { CarrierBillingRead, CarrierBillingUpdate };

/** HTTP status the backend returns when the AWB is already used in this tenant. */
export const DUPLICATE_AWB_STATUS = 409;

/**
 * Turns a service option code into its display label.
 *
 * @param option - Code from the API (may be absent on legacy rows).
 * @returns The label, the raw code for an unknown value, or null when absent.
 */
export function serviceOptionLabel(option: string | null | undefined): string | null {
  if (!option) return null;
  return SERVICE_OPTION_OPTIONS[option as ServiceOption]?.label ?? option;
}

/**
 * Tells whether an API error is the duplicate-AWB conflict.
 *
 * @param err - Error thrown by the request.
 * @returns True for an HTTP 409.
 */
export function isDuplicateAwbError(err: unknown): boolean {
  return err instanceof ApiError && err.status === DUPLICATE_AWB_STATUS;
}

/**
 * Reads the carrier booking (service option, AWB, charged values, gap) of a shipment.
 *
 * @param shipmentId - Shipment UUID.
 * @param tenantSlug - Tenant slug header.
 * @returns The backend's carrier billing view.
 */
export function fetchCarrierBilling(
  shipmentId: string,
  tenantSlug?: string | null,
): Promise<CarrierBillingRead> {
  return ShipmentsService.readShipmentCarrierBilling(
    shipmentId,
    tenantSlug,
  );
}

/**
 * Saves the Delhivery booking values ops copied from one.delhivery.com.
 *
 * @param shipmentId - Shipment UUID.
 * @param payload - AWB (required) plus the optional charged weight and amount.
 * @param tenantSlug - Tenant slug header.
 * @returns The updated carrier billing view, including the backend's gap verdict.
 */
export function saveCarrierBilling(
  shipmentId: string,
  payload: CarrierBillingUpdate,
  tenantSlug?: string | null,
): Promise<CarrierBillingRead> {
  return ShipmentsService.saveShipmentCarrierBilling(
    shipmentId,
    payload,
    tenantSlug,
  );
}

/** Payload for a direct Owner/Admin shipment price override or charge adjustment (#558 3c, #568). */
export interface AdminShipmentChargeCreate {
  override_total_price?: number | null;
  amount?: number | null;
  includes_gst?: boolean;
  label?: string;
}

/**
 * Applies a direct Owner/Admin charge adjustment on a shipment (#558 3c):
 * debits the customer's wallet, updates `total_logistics_cost`, and issues a GST Debit Note.
 *
 * @param shipmentId - Shipment UUID.
 * @param payload - Charge amount (₹) and reason label.
 * @param tenantSlug - Tenant slug header.
 * @returns The updated carrier billing view after the charge adjustment.
 */
export function applyAdminShipmentCharge(
  shipmentId: string,
  payload: AdminShipmentChargeCreate,
  tenantSlug?: string | null,
): Promise<CarrierBillingRead> {
  return ShipmentsService.createAdminShipmentCharge(
    shipmentId,
    payload,
    tenantSlug,
  );
}

/** Label + help text of the AWB field, per who carries the parcel. */
export interface AwbFieldCopy {
  label: string;
  description: string;
}


/**
 * AWB field copy for the carrier form: Prime runs on partner transporters (their AWB / LR),
 * Delhivery B2B cargo uses an LRN, every other option a Delhivery AWB.
 *
 * @param option - Booked service option (may be absent on legacy rows).
 * @returns Label and description for the AWB input.
 */
export function awbFieldCopy(option: string | null | undefined): AwbFieldCopy {
  if (option === ServiceOption.PRIME_SURFACE) {
    return {
      label: "Transporter AWB / LR number",
      description: "Enter the AWB or LR number the partner transporter gave for this shipment.",
    };
  }
  if (option === ServiceOption.DELHIVERY_B2B_SURFACE) {
    return {
      label: "Delhivery LRN",
      description: "Book on one.delhivery.com (B2B), then paste the LRN here.",
    };
  }
  return {
    label: "Delhivery AWB",
    description: "Book on one.delhivery.com, then paste the AWB here.",
  };
}
