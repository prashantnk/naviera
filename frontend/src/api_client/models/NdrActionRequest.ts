/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DocumentType } from './DocumentType';
import type { NdrAction } from './NdrAction';
/**
 * Merchant action on one on-hold shipment. Only the fields relevant to the
 * chosen action are read; the action itself is validated against the
 * server-side allowed-actions matrix.
 */
export type NdrActionRequest = {
    action: NdrAction;
    /**
     * New consignee name (same address and pincode)
     */
    consignee_name?: (string | null);
    consignee_phone?: (string | null);
    consignee_address_line1?: (string | null);
    consignee_address_line2?: (string | null);
    landmark?: (string | null);
    /**
     * Optional guard: address edits must stay within the same pincode
     */
    consignee_pincode?: (string | null);
    is_cod?: (boolean | null);
    eway_bill_number?: (string | null);
    invoice_number?: (string | null);
    document_type?: (DocumentType | null);
    document_url?: (string | null);
    appointment_start?: (string | null);
    appointment_end?: (string | null);
    preferred_date?: (string | null);
    notes?: (string | null);
    /**
     * PARTIAL_DELIVERY: boxes actually handed over (short shipment)
     */
    delivered_box_count?: (number | null);
    /**
     * PARTIAL_DELIVERY: revised goods COD for the boxes delivered (COD fee re-priced)
     */
    revised_cod_amount?: (number | null);
    /**
     * RETURN_TO_ORIGIN on a DAMAGED / SHORT_SHIPMENT exception: Logismart is at fault, so the RTO charge is waived. Tenant staff only (A-09); a shipper sending it gets 403
     */
    logismart_liable?: boolean;
};

