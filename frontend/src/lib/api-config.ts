// src/lib/api-config.ts
import { OpenAPI } from "@/api_client";
import axios, { type AxiosError } from "axios";
import { clearStoredSession, getSupabaseClient } from "./supabase";

/**
 * Window event fired when any API call is refused with 403, so `AuthGuard` can
 * re-check `/users/me` and show "Access not available" if the membership is gone
 * (e.g. the user row was removed while the tab stayed open).
 */
export const TENANT_ACCESS_CHECK_EVENT = "tenant-access-check";

/** HTTP status the backend returns for "signed in, but not allowed here". */
const FORBIDDEN_STATUS = 403;

/**
 * The profile endpoint `AuthGuard` uses for the re-check. Its own 403 must not
 * fire the event again, or a lost membership would loop forever.
 */
export const PROFILE_ENDPOINT_PATH = "/api/v1/users/me";

/** Interceptor id, so the handler is registered once per browser tab. */
let forbiddenInterceptorId: number | null = null;

/** HTTP status the backend returns when the bearer token is expired or invalid. */
const UNAUTHORIZED_STATUS = 401;

/**
 * Password login/signup endpoints answer 401 for a wrong password; that must
 * show the form error, never bounce to the login page.
 */
export const AUTH_ENDPOINT_PREFIX = "/api/v1/users/auth/";

/** Tenant of the current tab, kept in sync by `configureApiClient`. */
let activeTenantSlug: string | null = null;

/** Set once a redirect is under way, so parallel 401s navigate only once. */
let loginRedirectInProgress = false;

/**
 * Builds the login URL for an expired session, keeping where the user was.
 *
 * Works for both routing modes: on path routing (`/<slug>/shipments`) the
 * login page is `/<slug>/login`; on a subdomain / custom domain it is `/login`.
 *
 * @param tenantSlug - Current tenant slug.
 * @param pathname - `window.location.pathname`.
 * @param search - `window.location.search` (may be empty).
 * @returns `/…/login?next=<current path>`, or null when already on the login page.
 */
export function buildLoginRedirectUrl(
  tenantSlug: string,
  pathname: string,
  search: string,
): string | null {
  const slugPrefix = `/${tenantSlug}`;
  const isPathRouted = pathname === slugPrefix || pathname.startsWith(`${slugPrefix}/`);
  const loginPath = `${isPathRouted ? slugPrefix : ""}/login`;
  if (pathname === loginPath || pathname.startsWith(`${loginPath}/`)) return null;
  return `${loginPath}?next=${encodeURIComponent(`${pathname}${search}`)}`;
}

/**
 * Sends the user to the login page when a request that carried a bearer
 * token is refused with 401 (expired / revoked session, F-07). The stored
 * session is cleared first so the login page does not bounce straight back.
 *
 * @param status - HTTP status of the failed response, if any.
 * @param url - Request URL of the failed response, if known.
 * @param sentBearerToken - Whether the failed request carried `Authorization`.
 * @param navigate - Navigation function (injectable for tests).
 * @returns True when a redirect was started.
 */
export function redirectToLoginOnUnauthorized(
  status: number | undefined,
  url: string | undefined,
  sentBearerToken: boolean,
  navigate: (target: string) => void = (target) => window.location.assign(target),
): boolean {
  if (typeof window === "undefined" || status !== UNAUTHORIZED_STATUS) return false;
  if (!sentBearerToken || !activeTenantSlug || loginRedirectInProgress) return false;
  if (url?.includes(AUTH_ENDPOINT_PREFIX)) return false;
  const target = buildLoginRedirectUrl(
    activeTenantSlug,
    window.location.pathname,
    window.location.search,
  );
  if (!target) return false;
  loginRedirectInProgress = true;
  clearStoredSession(activeTenantSlug);
  navigate(target);
  return true;
}

/** Test hook: forget the active tenant and any redirect in progress. */
export function resetUnauthorizedRedirectStateForTests(tenantSlug: string | null = null): void {
  activeTenantSlug = tenantSlug;
  loginRedirectInProgress = false;
}

/**
 * Whether an axios request config carried a bearer token.
 *
 * @param headers - `error.config.headers` (AxiosHeaders or a plain object).
 * @returns True when an `Authorization` header was sent.
 */
function _sentBearerToken(headers: unknown): boolean {
  if (!headers || typeof headers !== "object") return false;
  const record = headers as Record<string, unknown> & { get?: (name: string) => unknown };
  const value = typeof record.get === "function" ? record.get("Authorization") : record.Authorization;
  return typeof value === "string" && value.startsWith("Bearer ");
}

/**
 * Tells `AuthGuard` to re-check access when a request was refused with 403.
 *
 * Role-based 403s (e.g. a read-only user on a write button) are harmless: the
 * re-check succeeds and nothing changes on screen.
 *
 * @param status - HTTP status of the failed response, if any.
 * @param url - Request URL of the failed response, if known.
 * @returns True when the event was dispatched.
 */
export function notifyTenantAccessCheck(status: number | undefined, url: string | undefined): boolean {
  if (typeof window === "undefined" || status !== FORBIDDEN_STATUS) return false;
  if (url?.split("?")[0].endsWith(PROFILE_ENDPOINT_PATH)) return false;
  window.dispatchEvent(new Event(TENANT_ACCESS_CHECK_EVENT));
  return true;
}

/**
 * Registers (once) a response interceptor on the axios instance the generated
 * client uses. It only observes failures and always re-throws them unchanged,
 * so every caller still receives its usual `ApiError`: a 403 asks `AuthGuard`
 * to re-check access, and a 401 on an authenticated call redirects to login.
 */
function registerForbiddenInterceptor(): void {
  if (typeof window === "undefined" || forbiddenInterceptorId !== null) return;
  forbiddenInterceptorId = axios.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      notifyTenantAccessCheck(error.response?.status, error.config?.url);
      redirectToLoginOnUnauthorized(
        error.response?.status,
        error.config?.url,
        _sentBearerToken(error.config?.headers),
      );
      return Promise.reject(error);
    },
  );
}

/**
 * Configures the auto-generated OpenAPI client with our multi-tenant auth.
 * We call this function before making API requests from the frontend.
 */
export function configureApiClient(tenantSlug: string) {
  activeTenantSlug = tenantSlug;

  // 1. Point it to the Next.js Proxy (which routes to FastAPI)
  OpenAPI.BASE = "";

  // 2. Dynamically inject headers for every request
  OpenAPI.HEADERS = async () => {
    const supabase = getSupabaseClient(tenantSlug);
    const {
      data: { session },
    } = await supabase.auth.getSession();

    return {
      "X-Tenant-Slug": tenantSlug,
      ...(session?.access_token
        ? { Authorization: `Bearer ${session.access_token}` }
        : {}),
    };
  };

  // 3. Any 403 asks AuthGuard to re-check this tenant membership; any 401 on a
  //    signed-in call sends the user to `/login?next=<here>`.
  registerForbiddenInterceptor();
}
