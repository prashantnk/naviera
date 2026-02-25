/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ActivityType } from './ActivityType';
/**
 * For Admins: The complete history of a shipment.
 */
export type ShipmentActivityRead = {
    id: string;
    timestamp: string;
    user_id: string;
    activity_type: ActivityType;
    summary?: (string | null);
    comment?: (string | null);
    is_public: boolean;
    diff?: Record<string, any>;
};

