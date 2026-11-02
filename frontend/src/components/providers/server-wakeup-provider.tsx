// frontend/src/components/providers/server-wakeup-provider.tsx
"use client";

import React, { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

/** Backend liveness endpoint (proxied by Next.js to FastAPI). */
export const HEALTH_ENDPOINT = "/health";
/** A health check slower than this counts as a failure (F-03: at least 10 s). */
export const HEALTH_CHECK_TIMEOUT_MS = 10_000;
/** Consecutive failed checks before the banner appears (one slow request is not an outage). */
export const FAILURES_BEFORE_BANNER = 2;
/** Delay between checks while the backend is unreachable (so the banner never shows before ~10 s). */
export const RETRY_INTERVAL_MS = 10_000;
/** Delay between keep-alive checks while the backend is healthy (14 min). */
export const KEEP_ALIVE_INTERVAL_MS = 840_000;

/** What the provider does after one health check. */
export interface WakeupDecision {
  /** Consecutive failures so far (0 after a success). */
  failures: number;
  /** Whether the non-blocking "connecting" banner is shown. */
  showBanner: boolean;
  /** When to run the next check. */
  nextDelayMs: number;
}

/**
 * Pure state transition for one health-check result.
 *
 * @param previousFailures - Consecutive failures before this check.
 * @param healthy - Whether this check succeeded within the timeout.
 * @returns The new failure count, banner visibility and next delay.
 */
export function nextWakeupDecision(previousFailures: number, healthy: boolean): WakeupDecision {
  if (healthy) {
    return { failures: 0, showBanner: false, nextDelayMs: KEEP_ALIVE_INTERVAL_MS };
  }
  const failures = previousFailures + 1;
  return {
    failures,
    showBanner: failures >= FAILURES_BEFORE_BANNER,
    nextDelayMs: RETRY_INTERVAL_MS,
  };
}

/**
 * One health check with a hard timeout.
 *
 * @returns True when `/health` answered 2xx within `HEALTH_CHECK_TIMEOUT_MS`.
 */
async function _checkHealth(): Promise<boolean> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);
  try {
    const res = await fetch(HEALTH_ENDPOINT, { signal: controller.signal, cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Watches backend availability (cold starts, restarts) WITHOUT blocking the
 * app (F-03): the page keeps rendering, a small banner appears only after
 * `FAILURES_BEFORE_BANNER` consecutive failed/slow checks, it disappears on
 * its own when the backend answers again, and nothing is reloaded, so
 * half-filled forms are never lost.
 */
export function ServerWakeupProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [showBanner, setShowBanner] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    let timerId: ReturnType<typeof setTimeout> | null = null;

    const runCheck = async () => {
      const healthy = await _checkHealth();
      if (cancelled) return;
      const decision = nextWakeupDecision(failures, healthy);
      failures = decision.failures;
      setShowBanner(decision.showBanner);
      timerId = setTimeout(runCheck, decision.nextDelayMs);
    };

    runCheck();

    return () => {
      cancelled = true;
      if (timerId) clearTimeout(timerId);
    };
  }, []);

  return (
    <>
      {children}
      {showBanner && (
        <div
          role="status"
          aria-live="polite"
          data-testid="server-wakeup.banner"
          className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] w-[calc(100%-2rem)] max-w-md flex items-start gap-3 rounded-xl border border-slate-200 bg-white/95 p-4 shadow-lg backdrop-blur animate-in fade-in slide-in-from-bottom-2 duration-300"
        >
          <Loader2 className="h-5 w-5 shrink-0 animate-spin text-primary mt-0.5" aria-hidden="true" />
          <div className="text-sm">
            <p className="font-semibold text-slate-900">Connecting to the server…</p>
            <p className="text-slate-600">
              This can take up to a minute. You can keep working; we&apos;ll
              reconnect automatically.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
