// frontend/src/components/team/user-edit-policy.ts
/**
 * What the signed-in Owner/Admin may change on another user, mirroring the backend
 * guard `TenantService._assert_owner_rules` (backend/app/services/tenants.py).
 *
 * The backend is the real gatekeeper (it answers 400/403). This map only decides
 * which role choices, status radios and menu items the Users page enables, so an
 * admin never clicks something the API would refuse with a generic error.
 *
 * Rules (Delhivery One `users`: only the Owner adds or changes Admins, the Owner
 * can't be removed, ownership moves by making another user Owner):
 * - Nobody changes their own role or deactivates themselves.
 * - The Owner can't be demoted or deactivated.
 * - Only the Owner can make someone Owner (transfer) or Admin, or change an Admin.
 * - Service scope (B2C / B2B) only applies to customers; staff always have both.
 *
 * Spring analogy: a `@PreAuthorize` table evaluated in the view layer.
 */
import { UserRole } from "@/api_client";

/** The minimal user shape the rules need (both actor and target). */
export interface PolicyUser {
  id: string;
  role: UserRole;
}

/** Edit permissions for one target user. */
export interface UserEditPolicy {
  /** True when no role in the list may be chosen. */
  roleLocked: boolean;
  /** Roles the actor may not pick (subset of all roles). */
  disabledRoles: ReadonlySet<UserRole>;
  /** True when Active / Inactive can't be changed. */
  statusLocked: boolean;
  /** Plain-English reason shown under the role list when something is locked. */
  lockReason: string | null;
  /** True when the quick B2C / B2B scope menu applies (customers only). */
  canChangeScope: boolean;
}

export const SELF_LOCK_REASON =
  "You can't change your own role or deactivate yourself. Ask the Owner.";
export const OWNER_LOCK_REASON =
  "The Owner can't be demoted or deactivated. To hand over the account, open another user and make them Owner.";
export const ADMIN_LOCK_REASON = "Only the Owner can change or deactivate an Admin.";
export const ADMIN_GRANT_REASON = "Only the Owner can make someone Owner or Admin.";

/** Roles only the Owner may grant. */
const OWNER_ONLY_GRANTS: readonly UserRole[] = [UserRole.OWNER, UserRole.ADMIN];

/** Every role, for fully locked lists. */
const ALL_ROLES: readonly UserRole[] = Object.values(UserRole);

/**
 * Builds a fully locked policy (no role choice, no status change).
 *
 * @param reason - Why the user can't be changed.
 * @param canChangeScope - Whether the scope menu still applies.
 */
function _locked(reason: string, canChangeScope: boolean): UserEditPolicy {
  return {
    roleLocked: true,
    disabledRoles: new Set(ALL_ROLES),
    statusLocked: true,
    lockReason: reason,
    canChangeScope,
  };
}

/**
 * Resolves what `actor` may change on `target`.
 *
 * @param actor - The signed-in Owner/Admin (null while the profile loads: everything locked).
 * @param target - The user being edited.
 * @returns The edit policy for the Users page.
 */
export function getUserEditPolicy(
  actor: PolicyUser | null | undefined,
  target: PolicyUser,
): UserEditPolicy {
  const isCustomer = target.role === UserRole.CUSTOMER;
  if (!actor) return _locked(ADMIN_GRANT_REASON, false);
  if (actor.id === target.id) return _locked(SELF_LOCK_REASON, false);
  if (target.role === UserRole.OWNER) return _locked(OWNER_LOCK_REASON, false);

  const actorIsOwner = actor.role === UserRole.OWNER;
  if (!actorIsOwner && target.role === UserRole.ADMIN) {
    return _locked(ADMIN_LOCK_REASON, false);
  }
  return {
    roleLocked: false,
    disabledRoles: new Set(actorIsOwner ? [] : OWNER_ONLY_GRANTS),
    statusLocked: false,
    lockReason: actorIsOwner ? null : ADMIN_GRANT_REASON,
    canChangeScope: isCustomer,
  };
}

/**
 * True when saving `nextRole` on `target` hands the account over (the actor becomes Admin).
 *
 * @param target - The user being edited.
 * @param nextRole - The role chosen in the dialog.
 */
export function isOwnershipTransfer(target: PolicyUser, nextRole: UserRole): boolean {
  return nextRole === UserRole.OWNER && target.role !== UserRole.OWNER;
}

/** Display order of roles in the Users table (team first, then customers). */
const ROLE_ORDER: readonly UserRole[] = [
  UserRole.OWNER,
  UserRole.ADMIN,
  UserRole.OPERATIONS_USER,
  UserRole.SUPPORT_USER,
  UserRole.READ_ONLY_USER,
  UserRole.CUSTOMER,
];

/**
 * Sorts users for the table: by role (Owner first, customers last), then by email.
 *
 * @param users - Users as returned by the API (not mutated).
 * @returns A new sorted array.
 */
export function sortUsersForTable<T extends PolicyUser & { email: string }>(users: readonly T[]): T[] {
  const rank = (role: UserRole) => {
    const index = ROLE_ORDER.indexOf(role);
    return index === -1 ? ROLE_ORDER.length : index;
  };
  return users
    .slice()
    .sort((a, b) => rank(a.role) - rank(b.role) || a.email.localeCompare(b.email));
}

/**
 * Formats a stored phone for the table: numbers saved with a country code keep it,
 * bare 10-digit numbers get "+91".
 *
 * @param phone - Phone as stored (digits with an optional leading "+").
 */
export function formatUserPhone(phone: string): string {
  return phone.startsWith("+") ? phone : `+91 ${phone}`;
}
