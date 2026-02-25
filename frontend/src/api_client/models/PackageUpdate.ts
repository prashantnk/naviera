/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Used for rditing packages inside a shipment.
 * - id: If present, we update the existing row. If None, we create a new row.
 */
export type PackageUpdate = {
    /**
     * Length in CM
     */
    length: number;
    /**
     * Breadth in CM
     */
    breadth: number;
    /**
     * Height in CM
     */
    height: number;
    /**
     * Weight in KG
     */
    weight: number;
    box_count?: number;
    description?: (string | null);
    is_fragile?: boolean;
    id?: (string | null);
};

