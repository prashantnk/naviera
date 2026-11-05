"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

/** Custom window event that programmatic callers may dispatch before `router.push`. */
export const NAVIERA_NAVIGATE_START_EVENT = "naviera:navigate-start";

/**
 * Imperatively triggers the global top navigation progress bar (e.g., before programmatic `router.push`).
 *
 * @param href - Optional target path; a target equal to the current URL only flashes the bar.
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
export const MIN_VISIBLE_MS = 180;

/**
 * Safety auto-clear (ms) for navigations that never change the URL (a link
 * whose click handler cancels it, a redirect back to the current page).
 */
export const SAFETY_TIMEOUT_MS = 8000;

/** Same-origin paths that answer with a file download instead of a page. */
const NON_PAGE_PATH_PATTERN = /^\/(?:api|supabase-proxy)\/|\.[a-z0-9]{2,5}$/i;

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

/** `pathname + search` of the address bar. */
function currentLocationKey(): string {
  return `${window.location.pathname}${window.location.search}`;
}

/**
 * Resolves a navigation target to the `pathname + search` it would render.
 *
 * @param rawHref - Absolute or relative URL.
 * @returns The route key, or `null` for cross-origin / malformed URLs.
 */
function resolveRouteKey(rawHref: string): string | null {
  try {
    const url = new URL(rawHref, window.location.href);
    if (url.origin !== window.location.origin) return null;
    return `${url.pathname}${url.search}`;
  } catch {
    return null;
  }
}

/**
 * Determines whether a clicked `<a>` element is an internal same-origin page navigation.
 *
 * @param anchor - Anchor element in the click path.
 * @returns Target `pathname + search` if internal navigation, or `null` otherwise.
 */
export function resolveInternalAnchorTarget(anchor: HTMLAnchorElement): string | null {
  const rawHref = anchor.getAttribute("href");
  if (!rawHref) return null;
  if (/^(#|mailto:|tel:|sms:|javascript:|blob:|data:)/i.test(rawHref)) {
    return null;
  }
  if (anchor.hasAttribute("download")) return null;
  const targetAttr = anchor.getAttribute("target");
  if (targetAttr && targetAttr !== "_self") return null;
  if ((anchor.getAttribute("rel") ?? "").split(/\s+/).includes("external")) return null;

  const routeKey = resolveRouteKey(rawHref);
  if (!routeKey) return null;
  const pathname = routeKey.split("?")[0];
  return NON_PAGE_PATH_PATTERN.test(pathname) ? null : routeKey;
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

  const resetBar = useCallback(() => {
    clearPendingNavElements();
    setIsActive(false);
    setProgress(0);
  }, []);

  const stopNavigation = useCallback(
    (immediate = false) => {
      clearTimers();
      if (immediate) {
        resetBar();
        return;
      }
      const elapsed = Date.now() - startedAtRef.current;
      const remaining = Math.max(0, MIN_VISIBLE_MS - elapsed);
      setProgress(100);
      finishTimerRef.current = setTimeout(resetBar, remaining);
    },
    [clearTimers, resetBar]
  );

  /**
   * Shows the bar for a navigation to `routeKey` (when known). A target equal
   * to the current URL cannot change the route, so it only flashes briefly.
   */
  const startNavigation = useCallback(
    (targetElement: Element | null, routeKey: string | null) => {
      clearTimers();
      clearPendingNavElements();
      if (targetElement) {
        targetElement.setAttribute("data-nav-pending", "true");
      }
      startedAtRef.current = Date.now();
      setIsActive(true);
      setProgress(38);

      if (routeKey !== null && routeKey === currentLocationKey()) {
        stopNavigation(false);
        return;
      }

      trickleTimerRef.current = setInterval(() => {
        setProgress((prev) => (prev >= 88 ? prev : prev + 10));
      }, 120);
      safetyTimerRef.current = setTimeout(resetBar, SAFETY_TIMEOUT_MS);
    },
    [clearTimers, resetBar, stopNavigation]
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
        if (destination !== null) startNavigation(anchor, destination);
        return;
      }

      const navTrigger = target.closest("[data-nav-trigger]");
      if (navTrigger) {
        const href = navTrigger.getAttribute("data-nav-trigger");
        startNavigation(navTrigger, href ? resolveRouteKey(href) : null);
      }
    };

    const handleCustomStart = (event: Event) => {
      const href = (event as CustomEvent<{ href?: string } | undefined>).detail?.href;
      startNavigation(null, href ? resolveRouteKey(href) : null);
    };

    // Back/forward: the address bar already shows the target; show the bar
    // only if the rendered route still has to catch up.
    const handlePopState = () => {
      if (currentLocationKey() !== lastRouteKeyRef.current) {
        startNavigation(null, null);
      }
    };

    document.addEventListener("click", handleDocumentClick, true);
    window.addEventListener(NAVIERA_NAVIGATE_START_EVENT, handleCustomStart);
    window.addEventListener("popstate", handlePopState);

    return () => {
      document.removeEventListener("click", handleDocumentClick, true);
      window.removeEventListener(NAVIERA_NAVIGATE_START_EVENT, handleCustomStart);
      window.removeEventListener("popstate", handlePopState);
      clearTimers();
      clearPendingNavElements();
    };
  }, [clearTimers, startNavigation]);

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
 * Next.js App Router settles the new route. Programmatic `router.push` calls
 * announce themselves with `triggerNavigationProgress(href)`; `history` is
 * deliberately not patched (Next.js calls `pushState` only after the new route
 * has committed, which would restart the bar after the navigation finished).
 */
export function NavigationProgress() {
  return (
    <Suspense fallback={null}>
      <NavigationProgressInner />
    </Suspense>
  );
}
