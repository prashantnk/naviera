// frontend/src/app/[tenant_slug]/(app)/pickup-requests/new/layout.tsx
import { CapabilityGuard } from "@/components/auth/capability-guard";

/**
 * Route guard for `/pickup-requests/new`: Read-Only and Support-User staff cannot book (backend
 * `assert_can_manage_shipments_or_pickups`), so opening the URL directly shows a clear
 * notice instead of a form that fails with a 403 on submit. Sidebar/header and any
 * parent guard (e.g. the B2B flow guard) still apply.
 */
export default function PickupRequestsNewLayout({ children }: { children: React.ReactNode }) {
  return (
    <CapabilityGuard
      capability="canBook"
      area="Pickup request bookings"
      reason="Read-Only and Support staff can view orders and pickups but cannot create them. Ask an Owner, Admin or Operations user."
    >
      {children}
    </CapabilityGuard>
  );
}
