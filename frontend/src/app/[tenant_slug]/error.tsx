// frontend/src/app/[tenant_slug]/error.tsx
"use client";

import { ErrorFallback } from "@/components/blocks/error-fallback";

/**
 * Error boundary for every tenant page (marketing, app and auth zones).
 * Neutral wording, logged with the server digest (F-12).
 */
export default function TenantError({
  error,
  retry,
  reset,
}: {
  error: Error & { digest?: string };
  retry?: () => void;
  reset?: () => void;
}) {
  return <ErrorFallback error={error} onRetry={retry ?? reset} source="tenant" />;
}
