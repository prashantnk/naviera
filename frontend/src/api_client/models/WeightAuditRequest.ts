/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type WeightAuditRequest = {
    /**
     * Audited chargeable weight in KG
     */
    audited_weight_kg: number;
    /**
     * Optional Admin final price override in INR (incl. GST; #568)
     */
    override_total_price?: (number | null);
};

