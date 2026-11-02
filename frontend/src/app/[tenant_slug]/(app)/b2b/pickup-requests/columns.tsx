// frontend/src/app/[tenant_slug]/(app)/b2b/pickup-requests/columns.tsx
/**
 * The B2B Pickup Requests columns are shared with B2C and live in
 * `components/pickups/pickup-request-columns.tsx`. Re-exported here so the
 * route folder keeps its conventional `columns.tsx` entry point.
 */
export { getPickupRequestColumns as getColumns } from "@/components/pickups/pickup-request-columns";
