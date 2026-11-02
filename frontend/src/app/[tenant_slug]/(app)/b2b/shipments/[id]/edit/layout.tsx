// frontend/src/app/[tenant_slug]/(app)/b2b/shipments/[id]/edit/layout.tsx
import { AdminOnlyGuard } from "@/components/auth/admin-only-guard";

/** Editing a booked LR is an Admin/Owner operation (the API returns 403 for merchants). */
export default function EditB2BShipmentLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminOnlyGuard action="Editing a booked LR" backHref="/b2b/shipments" backLabel="Back to B2B Shipments">
      {children}
    </AdminOnlyGuard>
  );
}
