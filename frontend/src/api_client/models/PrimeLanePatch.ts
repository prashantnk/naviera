/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Any subset of a lane's editable numbers plus `is_active`.
 * Unknown fields are rejected (422) so a typo never silently does nothing.
 */
export type PrimeLanePatch = {
    tat_hours?: (number | null);
    rate_per_kg?: (number | null);
    min_lr_charge?: (number | null);
    docket_charge?: (number | null);
    min_chargeable_kg?: (number | null);
    volumetric_divisor?: (number | null);
    max_dimension_cm?: (number | null);
    oda_per_kg?: (number | null);
    oda_min?: (number | null);
    odd_weight_per_kg?: (number | null);
    odd_weight_min?: (number | null);
    pickup_per_kg?: (number | null);
    pickup_min?: (number | null);
    door_delivery_per_kg?: (number | null);
    door_delivery_min?: (number | null);
    markup_percent?: (number | null);
    is_active?: (boolean | null);
};

