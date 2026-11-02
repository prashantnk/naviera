/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AppointmentListResponse } from '../models/AppointmentListResponse';
import type { AppointmentTab } from '../models/AppointmentTab';
import type { PickupStatus } from '../models/PickupStatus';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AppointmentsService {
    /**
     * List Appointments
     * B2B LRs per appointment tab (tenant-wide for staff, own LRs for customers) + tab counts.
     * @param tab pending, at_risk or booked
     * @param search LRN / Order ID / PO number
     * @param consignee
     * @param city
     * @param status
     * @param pddFrom Delivery-by date from
     * @param pddTo Delivery-by date to
     * @param expiredPoOnly
     * @param page
     * @param size
     * @param xTenantSlug
     * @returns AppointmentListResponse Successful Response
     * @throws ApiError
     */
    public static listAppointments(
        tab: AppointmentTab,
        search?: (string | null),
        consignee?: (string | null),
        city?: (string | null),
        status?: (PickupStatus | null),
        pddFrom?: (string | null),
        pddTo?: (string | null),
        expiredPoOnly: boolean = false,
        page: number = 1,
        size: number = 20,
        xTenantSlug?: (string | null),
    ): CancelablePromise<AppointmentListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/appointments',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'tab': tab,
                'search': search,
                'consignee': consignee,
                'city': city,
                'status': status,
                'pdd_from': pddFrom,
                'pdd_to': pddTo,
                'expired_po_only': expiredPoOnly,
                'page': page,
                'size': size,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
