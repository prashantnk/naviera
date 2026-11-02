// frontend/src/app/[tenant_slug]/(app)/wallet/layout.tsx
import { CapabilityGuard } from "@/components/auth/capability-guard";

/**
 * Route guard for `/wallet`: Support-User staff have no wallet of their own and
 * no tenant-wide finance access, so they see a clear notice instead of an empty
 * ₹0 page. Sidebar/header still come from `(app)/layout.tsx`.
 */
export default function WalletLayout({ children }: { children: React.ReactNode }) {
  return (
    <CapabilityGuard
      capability="canViewWallet"
      area="Wallet and ledger pages"
      reason="Support staff have no wallet, and the tenant-wide ledger is visible to Owner, Admin and Read-Only staff only."
    >
      {children}
    </CapabilityGuard>
  );
}
