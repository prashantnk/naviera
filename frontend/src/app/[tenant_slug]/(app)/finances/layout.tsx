// frontend/src/app/[tenant_slug]/(app)/finances/layout.tsx
import { CapabilityGuard } from "@/components/auth/capability-guard";

/**
 * Route-group guard for `/finances/*` (COD remittances, GST invoices and notes).
 * Mirrors backend `_finance_scope_user_id`: customers see their own documents,
 * owner / admin / read-only the whole tenant; operations and support staff get a
 * clear notice instead of a 403 toast. Sidebar/header still come from `(app)/layout.tsx`.
 */
export default function FinancesLayout({ children }: { children: React.ReactNode }) {
  return (
    <CapabilityGuard
      capability="canViewFinanceDocuments"
      area="Remittances and invoices"
      reason="Sellers' COD payouts and GST documents are visible to Owner, Admin and Read-Only staff only. Ask an Owner or Admin if you need a copy."
    >
      {children}
    </CapabilityGuard>
  );
}
