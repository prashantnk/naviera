/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Delhivery B2B Surface 'Shipment summary' stage counters (B2B flow).
 */
export type B2BStageSummary = {
    /**
     * OPEN + ASSIGNED — LRs created, awaiting pickup
     */
    lrs_manifested: number;
    /**
     * IN_TRANSIT
     */
    in_transit: number;
    /**
     * OUT_FOR_DELIVERY
     */
    out_for_delivery?: number;
    /**
     * EXCEPTION (all reasons, incl. appointment & consignee unreachable)
     */
    exceptions: number;
    /**
     * EXCEPTION with ndr_reason CUSTOMER_UNAVAILABLE
     */
    consignee_unreachable: number;
    /**
     * COMPLETED
     */
    delivered: number;
    /**
     * RTO_INITIATED
     */
    rto: number;
};

