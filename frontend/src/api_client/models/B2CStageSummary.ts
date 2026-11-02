/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Delhivery Domestic 'Order summary' stage counters (B2C flow).
 */
export type B2CStageSummary = {
    /**
     * OPEN — Ready to Ship
     */
    to_be_shipped: number;
    /**
     * ASSIGNED — linked to a Pickup Request
     */
    awaiting_pickup: number;
    /**
     * IN_TRANSIT
     */
    in_transit: number;
    /**
     * OUT_FOR_DELIVERY
     */
    out_for_delivery?: number;
    /**
     * EXCEPTION (NDR & other exceptions)
     */
    ndr_exceptions: number;
    /**
     * COMPLETED
     */
    delivered: number;
    /**
     * RTO_INITIATED
     */
    rto: number;
};

