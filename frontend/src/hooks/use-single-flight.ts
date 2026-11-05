// frontend/src/hooks/use-single-flight.ts
"use client";

import { useCallback, useRef, useState } from "react";

/** State and runner returned by {@link useSingleFlight}. */
export interface SingleFlight {
  /** True from the click until the running action settles. Drives `disabled` + spinner. */
  pending: boolean;
  /** Key passed to the running `run` call (e.g. a row id), or null when idle or unkeyed. */
  pendingKey: string | null;
  /**
   * Runs `action` unless another action from this hook is still in flight.
   *
   * @param action - The mutation to run (API call + toasts).
   * @param key - Optional id so a list can show the spinner on the clicked row only.
   * @returns The action's result, or `undefined` when the call was dropped as a duplicate.
   */
  run: <T>(action: () => Promise<T>, key?: string) => Promise<T | undefined>;
}

/**
 * Guards a mutation button against double submits.
 *
 * `disabled={pending}` only takes effect after React re-renders; the ref flips
 * synchronously, so a second click (or Enter) that lands before the re-render
 * is dropped instead of firing a duplicate request. Pending state is always
 * cleared in `finally`, so the button re-enables after success and failure.
 */
export function useSingleFlight(): SingleFlight {
  const inFlightRef = useRef(false);
  const [pending, setPending] = useState(false);
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const run = useCallback(async <T,>(action: () => Promise<T>, key?: string) => {
    if (inFlightRef.current) return undefined;
    inFlightRef.current = true;
    setPending(true);
    setPendingKey(key ?? null);
    try {
      return await action();
    } finally {
      inFlightRef.current = false;
      setPending(false);
      setPendingKey(null);
    }
  }, []);

  return { pending, pendingKey, run };
}
