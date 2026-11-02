// frontend/src/app/[tenant_slug]/(app)/shipments/[id]/edit/layout.tsx
import { AdminOnlyGuard } from "@/components/auth/admin-only-guard";

/** Route guard for `/shipments/[id]/edit`: allows bookers (own live orders, B9) and operators; blocks Support / Read-Only staff. */
export default function EditShipmentLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminOnlyGuard action="Editing a booked shipment" backHref="/shipments" backLabel="Back to Shipments">
      {children}
    </AdminOnlyGuard>
  );
}
