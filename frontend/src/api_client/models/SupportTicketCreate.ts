/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type SupportTicketCreate = {
    category_group?: string;
    sub_category: string;
    subject?: (string | null);
    description: string;
    tracking_id?: (string | null);
    shipment_id?: (string | null);
    cc_emails?: Array<string>;
    email_notifications?: boolean;
    attachment_url?: (string | null);
};

