// frontend/src/app/[tenant_slug]/(app)/b2b/layout.tsx
import { FlowAccessGuard } from "@/components/auth/flow-access-guard";

/**
 * Route-group guard for every `/b2b/*` page: B2C-only merchants who open a
 * B2B URL directly see a friendly "not enabled" card instead of the cargo
 * booking screens. Visual layout (sidebar/header) still comes from `(app)/layout.tsx`.
 */
export default function B2BLayout({ children }: { children: React.ReactNode }) {
  return <FlowAccessGuard flow="B2B">{children}</FlowAccessGuard>;
}
