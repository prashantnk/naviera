/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DimensionUnit } from './DimensionUnit';
import type { WeightUnit } from './WeightUnit';
/**
 * Used for rditing packages inside a shipment.
 * - id: If present, we update the existing row. If None, we create a new row.
 */
export type PackageUpdate = {
    /**
     * Length
     */
    length?: number;
    /**
     * Breadth
     */
    breadth?: number;
    /**
     * Height
     */
    height?: number;
    dimension_unit?: DimensionUnit;
    /**
     * Weight
     */
    weight: number;
    weight_unit?: WeightUnit;
    box_count?: number;
    description?: (string | null);
    is_fragile?: boolean;
    id?: (string | null);
};

