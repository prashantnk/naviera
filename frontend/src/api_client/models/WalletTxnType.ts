/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Ledger transaction categories matching Delhivery One's Unified Wallet Passbook:
 * - RECHARGE: Shipper tops up wallet balance via NPCI UPI QR ('upi://pay' + 12-digit UTR).
 * - SPEND: Immediate freight deduction when booking a Prepaid B2C parcel or B2B LR.
 * - REFUND: Automatic freight reversal when an OPEN/SCHEDULED shipment is cancelled before dispatch.
 * - COD_SETTLEMENT: 1-Click conversion of collected doorstep Cash-on-Delivery (COD) into usable wallet balance.
 * - WEIGHT_AUDIT_DEBIT: Automated differential debit when the Hub DWS laser scale measures higher weight than declared.
 * - FREIGHT_COLLECTION: Pending freight cleared by the merchant on a "Freight Collection" exception.
 * - ADDITIONAL_CHARGE: Acknowledged on-hold charges (e.g. Mathadi / union charges) on an "Additional Charges" exception.
 * - RTO_FREIGHT: The return (RTO) leg billed once per shipment (DB partial unique, migration M-B4).
 * - CHARGE_REVERSAL: Reversal of a separate charge (e.g. an Additional Charge waived by ops); own GST note.
 * The column is a plain VARCHAR(50) with no CHECK constraint, so new members need no migration.
 */
export enum WalletTxnType {
    RECHARGE = 'RECHARGE',
    SPEND = 'SPEND',
    REFUND = 'REFUND',
    COD_SETTLEMENT = 'COD_SETTLEMENT',
    WEIGHT_AUDIT_DEBIT = 'WEIGHT_AUDIT_DEBIT',
    FREIGHT_COLLECTION = 'FREIGHT_COLLECTION',
    ADDITIONAL_CHARGE = 'ADDITIONAL_CHARGE',
    RTO_FREIGHT = 'RTO_FREIGHT',
    CHARGE_REVERSAL = 'CHARGE_REVERSAL',
}
