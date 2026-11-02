// frontend/src/components/blocks/error-fallback.tsx
"use client";

import { Button } from "@/components/ui/button";
import { RefreshCw, TriangleAlert } from "lucide-react";
import { useEffect } from "react";

/** Heading shown by every route error boundary (neutral: no blame, no brand). */
export const ERROR_FALLBACK_TITLE = "Something went wrong";
/** Body text: temporary, actionable, and makes no claims about the cause. */
export const ERROR_FALLBACK_MESSAGE =
  "We couldn't load this page right now. This is usually temporary. Please try again in a moment.";

/**
 * Shared, tenant-neutral error UI for `app/global-error.tsx` and
 * `[tenant_slug]/error.tsx` (F-08, F-12).
 *
 * It logs the error once (with the server `digest`, which matches the server
 * log line) and offers "Try again", which re-fetches and re-renders the failed
 * segment; "Reload page" is the fallback when the segment cannot recover.
 */
export function ErrorFallback({
  error,
  onRetry,
  source,
}: {
  error: Error & { digest?: string };
  onRetry?: () => void;
  /** Which boundary caught it, for the log line (e.g. "global", "tenant"). */
  source: string;
}) {
  useEffect(() => {
    console.error(`[error-boundary:${source}]`, error.digest ?? "", error);
  }, [error, source]);

  return (
    <div
      role="alert"
      data-testid="error-fallback"
      className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-4 text-center"
    >
      <div className="max-w-md space-y-6">
        <div className="mx-auto w-20 h-20 bg-slate-200 rounded-full flex items-center justify-center">
          <TriangleAlert className="h-10 w-10 text-slate-600" aria-hidden="true" />
        </div>
        <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
          {ERROR_FALLBACK_TITLE}
        </h1>
        <p className="text-lg text-slate-500">{ERROR_FALLBACK_MESSAGE}</p>
        {error.digest && (
          <p className="text-xs text-slate-400 font-mono">Reference: {error.digest}</p>
        )}
        <div className="pt-2 flex flex-col sm:flex-row gap-3 justify-center">
          {onRetry && (
            <Button
              onClick={onRetry}
              size="lg"
              data-testid="error-fallback.retry"
              className="h-12 px-8 rounded-xl font-bold bg-slate-900 text-white"
            >
              <RefreshCw className="h-4 w-4 mr-2" aria-hidden="true" /> Try again
            </Button>
          )}
          <Button
            variant="outline"
            size="lg"
            className="h-12 px-8 rounded-xl font-bold"
            onClick={() => window.location.reload()}
          >
            Reload page
          </Button>
        </div>
      </div>
    </div>
  );
}
