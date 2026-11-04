"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

/** Custom window event that programmatic callers may dispatch before `router.push`. */
export const NAVIERA_NAVIGATE_START_EVENT = "naviera:navigate-start";

/**
 * Imperatively triggers the global top navigation progress bar (e.g., before programmatic `router.push`).
 *
 * @param href - Optional target path for same-route deduplication.
 */
export function triggerNavigationProgress(href?: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(NAVIERA_NAVIGATE_START_EVENT, {
      detail: { href },
    }),
  );
}

/** Minimum time (ms) the non-blocking top bar stays visible so clicks always feel acknowledged. */
const MIN_VISIBLE_MS = 180;

/** Safety auto-clear timeout (ms) in case a navigation is cancelled or intercepted. */
const SAFETY_TIMEOUT_MS = 3500;

/**
 * Clears `data-nav-pending="true"` from any previously clicked navigation elements.
 */
function clearPendingNavElements(): void {
  if (typeof document === "undefined") return;
  const pendingNodes = document.querySelectorAll('[data-nav-pending="true"]');
  pendingNodes.forEach((node) => {
    node.removeAttribute("data-nav-pending");
  });
}

/**
 * Determines whether a clicked `<a>` element is an internal same-origin route navigation.
 *
 * @param anchor - Anchor element in the click path.
 * @returns Target `pathname + search` if internal navigation, or `null` otherwise.
 */
function resolveInternalAnchorTarget(anchor: HTMLAnchorElement): string | null {
  const rawHref = anchor.getAttribute("href");
  if (!rawHref) return null;
  if (
    rawHref.startsWith("#") ||
    rawHref.startsWith("mailto:") ||
    rawHref.startsWith("tel:") ||
    rawHref.startsWith("javascript:")
  ) {
    return null;
  }
  if (anchor.hasAttribute("download")) return null;
  const targetAttr = anchor.getAttribute("target");
  if (targetAttr && targetAttr !== "_self") return null;

  try {
    const url = new URL(rawHref, window.location.origin);
    if (url.origin !== window.location.origin) return null;
    return `${url.pathname}${url.search}`;
  } catch {
    return null;
  }
}

function NavigationProgressInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchKey = searchParams?.toString() ?? "";
  const currentRouteKey = `${pathname ?? ""}${searchKey ? `?${searchKey}` : ""}`;

  const [isActive, setIsActive] = useState(false);
  const [progress, setProgress] = useState(0);

  const startedAtRef = useRef<number>(0);
  const lastRouteKeyRef = useRef<string>(currentRouteKey);
  const trickleTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const finishTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const safetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimers = useCallback(() => {
    if (trickleTimerRef.current !== null) {
      clearInterval(trickleTimerRef.current);
      trickleTimerRef.current = null;
    }
    if (finishTimerRef.current !== null) {
      clearTimeout(finishTimerRef.current);
      finishTimerRef.current = null;
    }
    if (safetyTimerRef.current !== null) {
      clearTimeout(safetyTimerRef.current);
      safetyTimerRef.current = null;
    }
  }, []);

  const stopNavigation = useCallback(
    (immediate = false) => {
      clearTimers();
      if (immediate) {
        clearPendingNavElements();
        setIsActive(false);
        setProgress(0);
        return;
      }

      const elapsed = Date.now() - startedAtRef.current;
      const remaining = Math.max(0, MIN_VISIBLE_MS - elapsed);
      setProgress(100);

      finishTimerRef.current = setTimeout(() => {
        clearPendingNavElements();
        setIsActive(false);
        setProgress(0);
      }, remaining);
    },
    [clearTimers]
  );

  const startNavigation = useCallback(
    (targetElement?: Element | null) => {
      clearTimers();
      clearPendingNavElements();
      if (targetElement) {
        targetElement.setAttribute("data-nav-pending", "true");
      }
      startedAtRef.current = Date.now();
      setIsActive(true);
      setProgress(38);

      trickleTimerRef.current = setInterval(() => {
        setProgress((prev) => {
          if (prev >= 88) return prev;
          return prev + 10;
        });
      }, 120);

      safetyTimerRef.current = setTimeout(() => {
        clearPendingNavElements();
        setIsActive(false);
        setProgress(0);
      }, SAFETY_TIMEOUT_MS);
    },
    [clearTimers]
  );

  // Settle progress bar when pathname + searchParams update.
  useEffect(() => {
    if (lastRouteKeyRef.current !== currentRouteKey) {
      lastRouteKeyRef.current = currentRouteKey;
      stopNavigation(true);
    }
  }, [currentRouteKey, stopNavigation]);

  useEffect(() => {
    const handleDocumentClick = (event: MouseEvent) => {
      if (event.defaultPrevented) return;
      if (event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

      const target = event.target;
      if (!(target instanceof Element)) return;

      const anchor = target.closest("a[href]") as HTMLAnchorElement | null;
      if (anchor) {
        const destination = resolveInternalAnchorTarget(anchor);
        if (!destination) return;
        const currentUrl = `${window.location.pathname}${window.location.search}`;
        startNavigation(anchor);
        if (destination === currentUrl) {
          // Clicking a link to the current route still gives brief tactile feedback.
          stopNavigation(false);
        }
        return;
      }

      const navTrigger = target.closest("[data-nav-trigger]");
      if (navTrigger) {
        startNavigation(navTrigger);
      }
    };

    const handleCustomStart = () => {
      startNavigation(null);
    };

    const originalPushState = window.history.pushState;
    window.history.pushState = function patchedPushState(
      data: unknown,
      unused: string,
      url?: string | URL | null
    ) {
      if (url) {
        try {
          const parsed = new URL(String(url), window.location.origin);
          const nextKey = `${parsed.pathname}${parsed.search}`;
          const currentKey = `${window.location.pathname}${window.location.search}`;
          if (parsed.origin === window.location.origin && nextKey !== currentKey) {
            queueMicrotask(() => startNavigation(null));
          }
        } catch {
          // Ignore malformed URLs in history state.
        }
      }
      return originalPushState.call(window.history, data, unused, url);
    };

    document.addEventListener("click", handleDocumentClick, true);
    window.addEventListener(NAVIERA_NAVIGATE_START_EVENT, handleCustomStart);

    return () => {
      document.removeEventListener("click", handleDocumentClick, true);
      window.removeEventListener(NAVIERA_NAVIGATE_START_EVENT, handleCustomStart);
      window.history.pushState = originalPushState;
      clearTimers();
      clearPendingNavElements();
    };
  }, [clearTimers, startNavigation, stopNavigation]);

  return (
    <div
      data-testid="global-navigation-progress"
      data-active={isActive ? "true" : "false"}
      data-pending={isActive ? "true" : "false"}
      role="progressbar"
      aria-label="Page navigation in progress"
      aria-hidden={!isActive}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={progress}
      className={
        isActive
          ? "fixed top-0 left-0 right-0 z-[9999] pointer-events-none opacity-100 transition-opacity duration-150"
          : "fixed top-0 left-0 right-0 z-[9999] pointer-events-none opacity-0 transition-opacity duration-150"
      }
    >
      <div className="h-1 w-full bg-primary/20 overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-150 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      {isActive && (
        <div
          data-testid="nav-ack-indicator"
          className="fixed top-2.5 right-3 z-[9999] flex items-center gap-1.5 rounded-full border border-primary/20 bg-background/95 px-2.5 py-1 text-[11px] font-semibold text-foreground shadow-sm backdrop-blur-xs"
        >
          <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
          <span>Loading…</span>
        </div>
      )}
    </div>
  );
}

/**
 * Global `< 16ms` click-acknowledgment & top navigation progress bar.
 *
 * Listens in the DOM capture phase for any internal `<a href="...">` or
 * `[data-nav-trigger]` click, immediately marks the clicked element with
 * `data-nav-pending="true"`, and renders a sleek top progress bar until
 * Next.js App Router settles the new route.
 */
export function NavigationProgress() {
  return (
    <Suspense fallback={null}>
      <NavigationProgressInner />
    </Suspense>
  );
}
