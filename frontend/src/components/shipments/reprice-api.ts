// frontend/src/components/shipments/reprice-api.ts
/**
 * Thin adapter over the Phase B re-pricing endpoints (plan B8):
 *   POST /api/v1/shipments/{id}/reprice-preview  (never writes)
 *   POST /api/v1/shipments/{id}/measurements     (Idempotency-Key)
 *   GET  /api/v1/shipments/{id}/charges          (charges history)
 *
 * The UI components import these functions instead of the generated service so the
 * generated method names live in one place. All money numbers are passed through as
 * the backend sent them (Zero Frontend Math).
 *
 * Spring analogy: a `@Component` facade around a Feign client.
 */
import {
  OpenAPI,
  ShipmentsService,
  type PickupRead,
  type PickupUpdate,
  type PackageCreate,
} from "@/api_client";
import { request as __request } from "@/api_client/core/request";

/** How the bill change is settled (decided by the backend per billing channel). */
export enum SettlementAction {
  DEBIT = "DEBIT",
  REFUND = "REFUND",
  COLLECTIBLE = "COLLECTIBLE",
  NONE = "NONE",
}

/** GST note issued for a bill change. */
export enum ChargeNoteType {
  DEBIT_NOTE = "DEBIT_NOTE",
  CREDIT_NOTE = "CREDIT_NOTE",
}

/** Who recorded a measurement (mirrors backend `MeasurementSource`). */
export enum MeasurementSource {
  PICKUP = "PICKUP",
  HUB = "HUB",
  ADMIN = "ADMIN",
}

/** One field the backend refused (H-7 zero price, H-8 service locked, H-12 / B9 edit window). */
export interface RejectedField {
  field: string;
  rule: string;
  message: string;
}

/** Server price preview for an edit (plan B1/B8). */
export interface RepricePreview {
  old_total: number;
  new_total: number;
  delta: number;
  old_chargeable_weight?: number | null;
  new_chargeable_weight?: number | null;
  new_pricing_breakdown?: Record<string, unknown> | null;
  settlement_action: SettlementAction;
  note_type?: ChargeNoteType | null;
  settlement_message?: string | null;
  old_cod_collectible?: number | null;
  new_cod_collectible?: number | null;
  price_changed: boolean;
  rejected_fields: RejectedField[];
}

/** One row of the charges history (a `shipment_charge_adjustments` row). */
export interface ChargeAdjustment {
  id: string;
  created_at: string;
  reason: string;
  old_total: number;
  new_total: number;
  delta: number;
  old_chargeable_weight?: number | null;
  new_chargeable_weight?: number | null;
  freight_payment_mode?: string | null;
  wallet_txn_id?: string | null;
  billing_invoice_id?: string | null;
  note_number?: string | null;
  note_type?: ChargeNoteType | null;
  actor_email?: string | null;
}

/** Body of POST /measurements: exactly one of `packages` or `weight_kg`. */
export interface MeasurementPayload {
  source: MeasurementSource;
  packages?: PackageCreate[];
  weight_kg?: number;
  override_total_price?: number;
  evidence_urls?: string[];
  remark?: string;
}

/** Response of POST /measurements. */
export interface MeasurementOutcome {
  shipment: PickupRead;
  adjustment: ChargeAdjustment | null;
}

/** Per-LR "Actual pieces" entry sent with the pickup dispatch (A-11). */
export interface DispatchMeasurement {
  shipment_id: string;
  packages?: PackageCreate[];
  actual_pieces?: number;
  evidence_urls?: string[];
  remark?: string;
}

/**
 *Asks the backend what an edit would cost, without saving anything.
 *
 * @param shipmentId - Shipment UUID.
 * @param change - PickupUpdate holding only the changed fields.
 * @param tenantSlug - Tenant slug header.
 * @returns The server preview (rejections come back as 200 with `rejected_fields`).
 */
export function fetchRepricePreview(
  shipmentId: string,
  change: PickupUpdate,
  tenantSlug?: string | null,
): Promise<RepricePreview> {
  return ShipmentsService.previewShipmentReprice(
    shipmentId,
    change,
    tenantSlug,
  ) as unknown as Promise<RepricePreview>;
}

/**
 * Records a measurement (pickup, hub or admin) that becomes the billing basis.
 *
 * @param shipmentId - Shipment UUID.
 * @param payload - Boxes or a weight-only entry.
 * @param idempotencyKey - One key per dialog submission (H-4).
 * @param tenantSlug - Tenant slug header.
 * @returns The updated shipment and the adjustment row (null when the bill did not move).
 */
export function recordShipmentMeasurement(
  shipmentId: string,
  payload: MeasurementPayload,
  idempotencyKey: string,
  tenantSlug?: string | null,
): Promise<MeasurementOutcome> {
  return __request(OpenAPI, {
    method: "POST",
    url: "/api/v1/shipments/{shipment_id}/measurements",
    path: {
      shipment_id: shipmentId,
    },
    headers: {
      "Idempotency-Key": idempotencyKey,
      "x-tenant-slug": tenantSlug,
    },
    body: payload,
    mediaType: "application/json",
    errors: {
      422: "Validation Error",
    },
  }) as unknown as Promise<MeasurementOutcome>;
}

/**
 * Lists every price change on a shipment, oldest first.
 *
 * @param shipmentId - Shipment UUID.
 * @param tenantSlug - Tenant slug header.
 * @returns Charges history rows.
 */
export function fetchShipmentCharges(
  shipmentId: string,
  tenantSlug?: string | null,
): Promise<ChargeAdjustment[]> {
  return ShipmentsService.listShipmentCharges(
    shipmentId,
    tenantSlug,
  ) as unknown as Promise<ChargeAdjustment[]>;
}

/**
 * Builds a `DispatchMeasurement` when the rider enters an "Actual pieces" box count
 * without manually overriding box dimensions/weight (A-11: Zero Frontend Math).
 * Sends only `{ shipment_id, actual_pieces }` so the backend scales declared package lines
 * (or records pending hub measurement for blind LRs) without inventing box dimensions.
 *
 * @param shipmentId - Shipment UUID.
 * @param boxCount - Actual pieces handed over at the doorstep.
 * @returns A `DispatchMeasurement` ready for `ManifestDispatchRequest.measurements`.
 */
export async function buildMeasurementForPieceCount(
  shipmentId: string,
  boxCount: number,
  _tenantSlug?: string | null,
  _knownShipment?: PickupRead | null,
): Promise<DispatchMeasurement> {
  return {
    shipment_id: shipmentId,
    actual_pieces: boxCount,
  };
}

/**
 * Creates a fresh Idempotency-Key for one money POST.
 *
 * @returns A random UUID string.
 */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
