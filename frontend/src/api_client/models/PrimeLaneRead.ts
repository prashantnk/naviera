/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PrimeDeliveryType } from './PrimeDeliveryType';
import type { PrimeLaneMode } from './PrimeLaneMode';
/**
 * One lane as shown in the staff lanes editor (zones by name).
 */
export type PrimeLaneRead = {
    id: string;
    origin_zone: string;
    dest_zone: string;
    mode: PrimeLaneMode;
    transporter_name: string;
    tat_hours: number;
    rate_per_kg: number;
    min_lr_charge: number;
    docket_charge: number;
    min_chargeable_kg: number;
    volumetric_divisor: number;
    max_dimension_cm: number;
    delivery_type: PrimeDeliveryType;
    oda_per_kg: number;
    oda_min: number;
    odd_weight_per_kg: number;
    odd_weight_min: number;
    pickup_per_kg: number;
    pickup_min: number;
    door_delivery_per_kg: number;
    door_delivery_min: number;
    markup_percent: number;
    is_active: boolean;
    updated_at: string;
};

