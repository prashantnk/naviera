// frontend/src/components/providers/workspace-flow-provider.tsx
"use client";

/**
 * Holds which business flow (B2C Express or B2B Cargo) the user is currently
 * working inside, and shares it between the header, sidebar and mobile drawer.
 *
 * Spring analogy: a session-scoped bean injected into every view. The rules
 * that decide the flow live in `@/lib/workspace-flow` (pure + unit-tested);
 * this provider only wires them to React state, the URL and `localStorage`.
 */
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { triggerNavigationProgress } from "@/components/ui/navigation-progress";
import {
  FLOW_DASHBOARD_HREF,
  ServiceFlow,
  getFlowStorageKey,
  parseServiceFlow,
  resolveActiveFlow,
  resolveFlowFromPath,
  resolveLockedFlow,
} from "@/lib/workspace-flow";
import { usePathname, useRouter } from "next/navigation";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

interface WorkspaceFlowContextType {
  /** Flow whose menu and dashboards are currently shown. */
  activeFlow: ServiceFlow;
  /** True only for users who may use both flows (BOTH scope, Admins, Owners). */
  canSwitchFlow: boolean;
  /** Switches to `flow` and navigates to that flow's dashboard. */
  switchFlow: (flow: ServiceFlow) => void;
}

const WorkspaceFlowContext = createContext<WorkspaceFlowContextType | undefined>(
  undefined
);

/**
 * Reads the remembered flow for a tenant from `localStorage`.
 *
 * @param tenantSlug - Active tenant slug.
 * @returns The saved flow, or `null` if none / storage is unavailable.
 */
function _readPersistedFlow(tenantSlug: string): ServiceFlow | null {
  try {
    return parseServiceFlow(window.localStorage.getItem(getFlowStorageKey(tenantSlug)));
  } catch {
    return null;
  }
}

/**
 * Remembers the chosen flow for a tenant in `localStorage`.
 *
 * @param tenantSlug - Active tenant slug.
 * @param flow - Flow to remember.
 */
function _persistFlow(tenantSlug: string, flow: ServiceFlow): void {
  try {
    window.localStorage.setItem(getFlowStorageKey(tenantSlug), flow);
  } catch {
    // Storage can be blocked (private mode / quota); the choice simply won't persist.
  }
}

export function WorkspaceFlowProvider({ children }: { children: React.ReactNode }) {
  const { tenantSlug, routeTo } = useTenant();
  const { canAccessB2C, canAccessB2B } = useUser();
  const pathname = usePathname();
  const router = useRouter();

  const canSwitchFlow = canAccessB2C && canAccessB2B;
  const lockedFlow = resolveLockedFlow(canAccessB2C, canAccessB2B);
  const pathFlow = resolveFlowFromPath(pathname, tenantSlug);

  const [savedFlow, setSavedFlow] = useState<ServiceFlow | null>(null);

  // Restore the remembered choice after mount (localStorage is browser-only,
  // so reading it during render would cause a hydration mismatch).
  useEffect(() => {
    setSavedFlow(_readPersistedFlow(tenantSlug));
  }, [tenantSlug]);

  // Opening a flow-specific URL directly (e.g. a shared /b2b/shipments link)
  // moves the user into that flow and remembers it for shared pages.
  useEffect(() => {
    if (!canSwitchFlow || !pathFlow) return;
    setSavedFlow(pathFlow);
    _persistFlow(tenantSlug, pathFlow);
  }, [canSwitchFlow, pathFlow, tenantSlug]);

  const switchFlow = useCallback(
    (flow: ServiceFlow) => {
      if (!canSwitchFlow) return;
      setSavedFlow(flow);
      _persistFlow(tenantSlug, flow);
      const targetHref = routeTo(FLOW_DASHBOARD_HREF[flow]);
      triggerNavigationProgress(targetHref);
      router.push(targetHref);
    },
    [canSwitchFlow, tenantSlug, router, routeTo]
  );

  const value = useMemo<WorkspaceFlowContextType>(
    () => ({
      activeFlow: resolveActiveFlow(lockedFlow, pathFlow, savedFlow),
      canSwitchFlow,
      switchFlow,
    }),
    [lockedFlow, pathFlow, savedFlow, canSwitchFlow, switchFlow]
  );

  return (
    <WorkspaceFlowContext.Provider value={value}>{children}</WorkspaceFlowContext.Provider>
  );
}

export function useWorkspaceFlow(): WorkspaceFlowContextType {
  const context = useContext(WorkspaceFlowContext);
  if (context === undefined) {
    throw new Error("useWorkspaceFlow must be used within a WorkspaceFlowProvider");
  }
  return context;
}
