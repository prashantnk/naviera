/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ServiceScope } from './ServiceScope';
import type { UserRole } from './UserRole';
export type UserRead = {
    id: string;
    email: string;
    full_name?: (string | null);
    phone?: (string | null);
    is_active: boolean;
    role: UserRole;
    service_scope?: ServiceScope;
    tenant_id: string;
    created_at?: (string | null);
    b2b_request_status?: (string | null);
    company_name?: (string | null);
    gstin?: (string | null);
    pan?: (string | null);
    b2b_requested_at?: (string | null);
    account_type?: (string | null);
    same_as_tenant_gstin?: (boolean | null);
    billing_address?: (string | null);
    gstin_status?: (string | null);
    company_details_locked?: boolean;
};

