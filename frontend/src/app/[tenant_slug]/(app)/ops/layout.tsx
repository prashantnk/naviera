// frontend/src/app/[tenant_slug]/(app)/ops/layout.tsx
import { CapabilityGuard } from "@/components/auth/capability-guard";

/**
 * Route-group guard for `/ops` (pickups, dispatch, OTP delivery, NDR, hub measurements).
 * Mirrors backend `assert_can_manage_shipments_or_pickups` + `assert_not_read_only`: only
 * Owner, Admin and Operations staff run field operations. Support and Read-Only staff (and
 * customers) who open the URL directly get a clear notice instead of buttons that answer
 * 403. Sidebar/header still come from `(app)/layout.tsx`.
 */
export default function OpsLayout({ children }: { children: React.ReactNode }) {
  return (
    <CapabilityGuard
      capability="canOperate"
      area="Operations tools"
      reason="The Ops Control Tower is for Owner, Admin and Operations staff. Ask an Owner or Admin if you need operations access."
    >
      {children}
    </CapabilityGuard>
  );
}
