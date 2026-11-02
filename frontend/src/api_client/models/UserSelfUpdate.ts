/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SellerCompanyDetailsSubmit } from './SellerCompanyDetailsSubmit';
/**
 * Self-service profile edit (any signed-in user): display name, phone, company details.
 */
export type UserSelfUpdate = {
    full_name?: (string | null);
    phone?: (string | null);
    company_details?: (SellerCompanyDetailsSubmit | null);
};

