// frontend/src/lib/safe-redirect.ts
/**
 * Guards post-login redirects (`?next=`) against open-redirect attacks.
 *
 * Only same-origin, tenant-relative paths are allowed (e.g. `/shipments/123`).
 * Anything that could leave the site, such as `//evil.com`, `/\evil.com`,
 * `https://evil.com` or `javascript:alert(1)`, falls back to the default.
 */

/** Default destination after a successful login. */
export const DEFAULT_POST_LOGIN_PATH = "/dashboard";

/** Characters that make browsers treat a path as protocol-relative or scheme-bearing. */
const UNSAFE_PATH_PATTERN = /^\/[\/\\]|[\u0000-\u001f]|:/;

/**
 * Returns `candidate` when it is a safe in-app path, otherwise the fallback.
 *
 * @param candidate - Raw value read from the `next` query parameter.
 * @param fallback - Path used when the candidate is missing or unsafe.
 * @returns A path beginning with a single `/` that stays on the current origin.
 */
export function sanitizeNextPath(
  candidate: string | null | undefined,
  fallback: string = DEFAULT_POST_LOGIN_PATH
): string {
  if (!candidate) return fallback;
  const trimmed = candidate.trim();
  if (!trimmed.startsWith("/")) return fallback;
  if (UNSAFE_PATH_PATTERN.test(trimmed)) return fallback;
  return trimmed;
}
