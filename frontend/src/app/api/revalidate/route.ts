// frontend/src/app/api/revalidate/route.ts

import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

/**
 * Server-only secret for trusted machine-to-machine callers (CI, backend webhooks).
 * There is deliberately NO fallback value: if the env var is unset, secret-based
 * calls are rejected and only authenticated tenant admins can revalidate.
 */
const REVALIDATION_SECRET = process.env.REVALIDATION_SECRET;

/** FastAPI base URL used to verify the caller's identity and role. */
const BACKEND_URL = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

/** Roles allowed to purge their own tenant's cached profile. */
const ADMIN_ROLES: ReadonlySet<string> = new Set(["admin", "owner"]);

/** Header carrying the server-to-server secret (never sent from browsers). */
const SECRET_HEADER = "x-revalidation-secret";

interface RevalidateBody {
  key?: string;
}

/**
 * Builds the cache tag used by `getTenantBySlug` for a tenant.
 *
 * @param slug - Tenant slug, e.g. `logismart`.
 * @returns The tag string `tenant-<slug>`.
 */
function _tenantTag(slug: string): string {
  return `tenant-${slug}`;
}

/**
 * Checks the machine-to-machine secret header against the server env value.
 *
 * @param request - Incoming request.
 * @returns True only when a secret is configured AND matches.
 */
function _hasValidServerSecret(request: NextRequest): boolean {
  const provided = request.headers.get(SECRET_HEADER);
  return Boolean(REVALIDATION_SECRET) && provided === REVALIDATION_SECRET;
}

/**
 * Verifies the caller is an Admin/Owner of `tenantSlug` by asking the backend.
 *
 * @param authorization - The caller's `Authorization: Bearer <jwt>` header.
 * @param tenantSlug - Tenant whose cache the caller wants to purge.
 * @returns True when the backend confirms an admin/owner role for that tenant.
 */
async function _isTenantAdmin(authorization: string | null, tenantSlug: string): Promise<boolean> {
  if (!authorization || !authorization.startsWith("Bearer ")) return false;
  try {
    const res = await fetch(`${BACKEND_URL}/api/v1/users/me`, {
      headers: { Authorization: authorization, "X-Tenant-Slug": tenantSlug },
      cache: "no-store",
    });
    if (!res.ok) return false;
    const profile = (await res.json()) as { role?: string };
    return Boolean(profile.role && ADMIN_ROLES.has(profile.role));
  } catch {
    return false;
  }
}

/**
 * POST /api/revalidate
 *
 * Two ways to authorise:
 * 1. **Tenant admin (browser):** `Authorization: Bearer <supabase jwt>` + body `{ key: "<tenant_slug>" }`.
 *    The backend confirms the caller is an admin/owner of that tenant; only that
 *    tenant's tag is purged.
 * 2. **Server-to-server:** header `x-revalidation-secret: <REVALIDATION_SECRET>`.
 *    May purge one tenant (`key`) or everything (no `key`).
 *
 * No secret is ever accepted from the query string or embedded in client code.
 */
export async function POST(request: NextRequest) {
  let body: RevalidateBody = {};
  try {
    body = (await request.json()) as RevalidateBody;
  } catch {
    body = {};
  }
  const key = typeof body.key === "string" ? body.key.trim() : "";

  try {
    if (_hasValidServerSecret(request)) {
      if (key) {
        revalidateTag(_tenantTag(key), "default");
        return NextResponse.json({ revalidated: true, scope: _tenantTag(key) });
      }
      revalidatePath("/", "layout");
      return NextResponse.json({ revalidated: true, scope: "all" });
    }

    if (!key) {
      return NextResponse.json({ message: "Tenant key is required" }, { status: 400 });
    }

    const isAdmin = await _isTenantAdmin(request.headers.get("authorization"), key);
    if (!isAdmin) {
      return NextResponse.json({ message: "Not authorised to revalidate this tenant" }, { status: 403 });
    }

    revalidateTag(_tenantTag(key), "default");
    return NextResponse.json({ revalidated: true, scope: _tenantTag(key) });
  } catch (err) {
    return NextResponse.json(
      { message: "Failed to revalidate", error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
