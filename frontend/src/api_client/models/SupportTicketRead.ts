/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type SupportTicketRead = {
    id: string;
    tenant_id: string;
    user_id: string;
    ticket_number: string;
    shipment_id?: (string | null);
    tracking_id?: (string | null);
    category_group?: string;
    sub_category: string;
    subject: string;
    description: string;
    status?: string;
    cc_emails?: Array<string>;
    email_notifications?: boolean;
    raised_by_email?: (string | null);
    created_at: string;
    updated_at: string;
};

