// frontend/src/lib/workspace-flow.ts
/**
 * Pure (framework-free) logic behind the "Choose your flow" switcher.
 *
 * Kept separate from the React provider so the resolution rules can be unit
 * tested without rendering components. Spring analogy: this is the stateless
 * `@Component` utility, while `WorkspaceFlowProvider` is the session-scoped bean
 * that holds the user's current choice.
 */

/** The two business flows a user can work inside. */
export enum ServiceFlow {
  B2C = "B2C",
  B2B = "B2B",
}

/** Flow used when nothing else (scope, URL, saved choice) decides it. */
export const DEFAULT_SERVICE_FLOW: ServiceFlow = ServiceFlow.B2C;

/** Prefix of the per-tenant `localStorage` key that remembers the choice. */
export const FLOW_STORAGE_KEY_PREFIX = "naviera-flow-";

/** Landing page each flow navigates to when the user switches into it. */
export const FLOW_DASHBOARD_HREF: Record<ServiceFlow, string> = {
  [ServiceFlow.B2C]: "/dashboard",
  [ServiceFlow.B2B]: "/b2b/dashboard",
};

/** Route prefix that marks every B2B Cargo page (incl. `/b2b/appointments`). */
const B2B_ROUTE_PREFIX = "/b2b";

/** Route prefixes that only exist in the B2C Express flow. */
const B2C_ONLY_ROUTE_PREFIXES: readonly string[] = [
  "/dashboard",
  "/shipments",
  "/delivery-exceptions",
  "/rate-calculator",
  "/pickup-requests",
];

/** Route prefixes shared by both B2C Express and B2B Cargo flows. */
export const SHARED_ROUTE_PREFIXES: readonly string[] = [
  "/wallet",
  "/address-book",
  "/finances",
  "/disputes",
  "/support",
  "/ops",
  "/team",
  "/settings",
];

/**
 * Checks whether `path` equals `prefix` or is nested beneath it.
 *
 * @param path - Tenant-relative path, e.g. `/b2b/shipments/123`.
 * @param prefix - Route prefix, e.g. `/b2b`.
 * @returns True when the path belongs to the prefix's route tree.
 */
function _matchesRoutePrefix(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`);
}

/**
 * Strips the `/<tenant_slug>` segment used in path-routing mode.
 *
 * In subdomain mode the browser path has no tenant segment, so it is returned
 * unchanged.
 *
 * @param pathname - Browser pathname from `usePathname()`.
 * @param tenantSlug - Active tenant slug, e.g. `logismart`.
 * @returns Tenant-relative path that always starts with `/`.
 */
export function toTenantRelativePath(pathname: string, tenantSlug: string): string {
  const tenantPrefix = `/${tenantSlug}`;
  if (pathname === tenantPrefix) return "/";
  if (pathname.startsWith(`${tenantPrefix}/`)) {
    return pathname.substring(tenantPrefix.length);
  }
  return pathname || "/";
}

/**
 * Infers the flow from the current URL.
 *
 * @param pathname - Browser pathname (may be null during the first render).
 * @param tenantSlug - Active tenant slug.
 * @returns The flow that owns the page, or `null` for shared pages such as
 *   `/wallet`, `/address-book`, `/finances`, `/disputes`, `/support`, `/ops`,
 *   `/team`, and `/settings`.
 */
export function resolveFlowFromPath(
  pathname: string | null,
  tenantSlug: string
): ServiceFlow | null {
  if (!pathname) return null;
  const relativePath = toTenantRelativePath(pathname, tenantSlug);
  if (_matchesRoutePrefix(relativePath, B2B_ROUTE_PREFIX)) return ServiceFlow.B2B;
  if (SHARED_ROUTE_PREFIXES.some((prefix) => _matchesRoutePrefix(relativePath, prefix))) {
    return null;
  }
  const isB2COnlyRoute = B2C_ONLY_ROUTE_PREFIXES.some((prefix) =>
    _matchesRoutePrefix(relativePath, prefix)
  );
  return isB2COnlyRoute ? ServiceFlow.B2C : null;
}

/**
 * Returns the flow a single-service user is locked into.
 *
 * @param canAccessB2C - Whether the user may use B2C Express.
 * @param canAccessB2B - Whether the user may use B2B Cargo.
 * @returns The only permitted flow, or `null` when the user may switch.
 */
export function resolveLockedFlow(
  canAccessB2C: boolean,
  canAccessB2B: boolean
): ServiceFlow | null {
  if (canAccessB2C && !canAccessB2B) return ServiceFlow.B2C;
  if (canAccessB2B && !canAccessB2C) return ServiceFlow.B2B;
  return null;
}

/**
 * Picks the active flow using the precedence: scope lock → URL → saved
 * choice → default.
 *
 * @param lockedFlow - Result of `resolveLockedFlow`.
 * @param pathFlow - Result of `resolveFlowFromPath`.
 * @param savedFlow - The user's remembered choice, if any.
 * @returns The flow the UI should render.
 */
export function resolveActiveFlow(
  lockedFlow: ServiceFlow | null,
  pathFlow: ServiceFlow | null,
  savedFlow: ServiceFlow | null
): ServiceFlow {
  return lockedFlow ?? pathFlow ?? savedFlow ?? DEFAULT_SERVICE_FLOW;
}

/**
 * Narrows an arbitrary stored string to a valid `ServiceFlow`.
 *
 * @param value - Raw value read from storage.
 * @returns The matching flow, or `null` for unknown / missing values.
 */
export function parseServiceFlow(value: string | null): ServiceFlow | null {
  if (value === ServiceFlow.B2C) return ServiceFlow.B2C;
  if (value === ServiceFlow.B2B) return ServiceFlow.B2B;
  return null;
}

/**
 * Builds the per-tenant storage key so choices never leak across tenants.
 *
 * @param tenantSlug - Active tenant slug.
 * @returns Storage key, e.g. `naviera-flow-logismart`.
 */
export function getFlowStorageKey(tenantSlug: string): string {
  return `${FLOW_STORAGE_KEY_PREFIX}${tenantSlug}`;
}
