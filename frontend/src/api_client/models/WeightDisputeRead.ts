/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type WeightDisputeRead = {
    id: string;
    tenant_id: string;
    merchant_user_id: string;
    /**
     * Merchant (customer) email, filled for tenant-wide staff views.
     */
    merchant_email?: (string | null);
    shipment_id?: (string | null);
    tracking_id: string;
    order_reference_id?: (string | null);
    shipment_status?: string;
    manifested_weight_g: number;
    charged_weight_g: number;
    claimed_weight_g?: (number | null);
    manifested_dims?: string;
    charged_dims?: string;
    shipping_cost_inr?: number;
    shipment_value_inr?: number;
    cost_diff_inr?: number;
    sorter_image_url?: (string | null);
    claim_status?: string;
    claim_remarks?: (string | null);
    raised_at: string;
    updated_at: string;
};

