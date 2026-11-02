/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SupportTicketCreate } from '../models/SupportTicketCreate';
import type { SupportTicketDetailRead } from '../models/SupportTicketDetailRead';
import type { SupportTicketMessageCreate } from '../models/SupportTicketMessageCreate';
import type { SupportTicketRead } from '../models/SupportTicketRead';
import type { SupportTicketStatusUpdate } from '../models/SupportTicketStatusUpdate';
import type { SupportTicketSummary } from '../models/SupportTicketSummary';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SupportTicketsService {
    /**
     * List Support Tickets
     * Lists SupportTicket rows (Customer sees own; Admin sees all in tenant).
     * @param status Filter by OPEN, RESOLVED, or CLOSED
     * @param search
     * @param xTenantSlug
     * @returns SupportTicketRead Successful Response
     * @throws ApiError
     */
    public static listSupportTickets(
        status?: (string | null),
        search?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<SupportTicketRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/support-tickets',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'status': status,
                'search': search,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Support Ticket
     * Creates a SupportTicket with an initial thread message.
     * @param requestBody
     * @param xTenantSlug
     * @returns SupportTicketDetailRead Successful Response
     * @throws ApiError
     */
    public static createSupportTicket(
        requestBody: SupportTicketCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<SupportTicketDetailRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/support-tickets',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Support Ticket Summary
     * Home-dashboard Support card counters (declared before `/{ticket_id}`).
     * @param xTenantSlug
     * @returns SupportTicketSummary Successful Response
     * @throws ApiError
     */
    public static getSupportTicketSummary(
        xTenantSlug?: (string | null),
    ): CancelablePromise<SupportTicketSummary> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/support-tickets/summary',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Support Ticket
     * Returns a SupportTicket and all thread messages.
     * @param ticketId
     * @param xTenantSlug
     * @returns SupportTicketDetailRead Successful Response
     * @throws ApiError
     */
    public static getSupportTicket(
        ticketId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<SupportTicketDetailRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/support-tickets/{ticket_id}',
            path: {
                'ticket_id': ticketId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Add Support Ticket Message
     * Appends a reply message to a SupportTicket (reopening RESOLVED tickets on customer reply).
     * @param ticketId
     * @param requestBody
     * @param xTenantSlug
     * @returns SupportTicketDetailRead Successful Response
     * @throws ApiError
     */
    public static addSupportTicketMessage(
        ticketId: string,
        requestBody: SupportTicketMessageCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<SupportTicketDetailRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/support-tickets/{ticket_id}/messages',
            path: {
                'ticket_id': ticketId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Support Ticket Status
     * Updates SupportTicket status (OPEN, RESOLVED, CLOSED).
     * @param ticketId
     * @param requestBody
     * @param xTenantSlug
     * @returns SupportTicketDetailRead Successful Response
     * @throws ApiError
     */
    public static updateSupportTicketStatus(
        ticketId: string,
        requestBody: SupportTicketStatusUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<SupportTicketDetailRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/support-tickets/{ticket_id}/status',
            path: {
                'ticket_id': ticketId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
