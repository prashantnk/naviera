/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Owner/Admin bidirectional shipment price override or charge adjustment (#558 3c, #568).
 * Supports either:
 * - `override_total_price`: sets the new final billed price (₹ incl. GST), crediting the
 * customer's wallet + GST Credit Note when lower than the current bill, or debiting the
 * customer's wallet + GST Debit Note when higher; OR
 * - `amount`: adds an extra charge (₹) on top of the current bill.
 */
export type AdminShipmentChargeCreate = {
    /**
     * New final total shipment price in INR (incl. 18% GST). Credits wallet if lower, debits if higher.
     */
    override_total_price?: (number | null);
    /**
     * Additional charge in INR (GST-inclusive when includes_gst=True, else pre-GST).
     */
    amount?: (number | null);
    /**
     * True when `amount` already includes 18% GST; False to add 18% GST on top.
     */
    includes_gst?: boolean;
    /**
     * Short label / reason recorded on the bill adjustment, wallet ledger, and GST Credit/Debit Note.
     */
    label?: string;
};

