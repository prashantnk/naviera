/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ServiceScope } from './ServiceScope';
import type { UserRole } from './UserRole';
export type UserUpdate = {
    full_name?: (string | null);
    phone?: (string | null);
    role?: (UserRole | null);
    is_active?: (boolean | null);
    service_scope?: (ServiceScope | null);
    company_name?: (string | null);
    gstin?: (string | null);
    pan?: (string | null);
    account_type?: (string | null);
    same_as_tenant_gstin?: (boolean | null);
};

