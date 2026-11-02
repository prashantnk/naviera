// frontend/src/app/global-error.tsx
"use client";

import { ErrorFallback } from "@/components/blocks/error-fallback";
import "./globals.css";

/**
 * Last-resort error boundary (F-08): replaces the root layout when it, or a
 * tenant layout (e.g. the tenant config could not be loaded, F-12), throws.
 * It must render its own <html>/<body>, so it imports the global styles.
 */
export default function GlobalError({
  error,
  retry,
  reset,
}: {
  error: Error & { digest?: string };
  retry?: () => void;
  reset?: () => void;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <title>Something went wrong</title>
        <ErrorFallback error={error} onRetry={retry ?? reset} source="global" />
      </body>
    </html>
  );
}
