// frontend/src/lib/mvp-scope.ts
/**
 * MVP scope switches (owner decisions 2026-10-30, fix plan WP0).
 *
 * Each switch mirrors a backend guard that rejects the same action with a 400,
 * so the UI never offers something the API refuses. Re-enabling a feature after
 * the MVP is a one-line change here plus the matching backend flag.
 */

/**
 * B2B reverse LRs (cargo returns) are switched off for the MVP. B2C returns
 * (DTO) stay available. Existing B2B reverse LRs remain viewable.
 */
export const B2B_REVERSE_BOOKING_ENABLED: boolean = false;
