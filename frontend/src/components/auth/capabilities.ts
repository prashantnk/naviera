// frontend/src/components/auth/capabilities.ts
/**
 * Frontend mirror of the backend role rules in `backend/app/core/permissions.py`.
 *
 * The backend is always the real gatekeeper (it returns 403). This map only
 * decides which buttons and menu entries we SHOW, so staff never see actions
 * the API would refuse. Keep both files in sync when a rule changes.
 *
 * Spring Boot analogy: a `@PreAuthorize("hasAnyRole(...)")` table, evaluated
 * once per user and exposed to the view layer.
 */
import { UserRole } from "@/api_client";

/** Every UI capability, one boolean per backend rule. */
export interface UserCapabilities {
  /** Any LogiSmart team member (owner, admin, operations, support, read-only). */
  isStaff: boolean;
  /** Invite / edit users and roles (`is_tenant_admin`). */
  canManageTeam: boolean;
  /** Edit workspace settings, branding, rate card (`is_tenant_admin`). */
  canManageSettings: boolean;
  /** Create remittances / invoices, approve recharges, resolve disputes (`is_tenant_admin`). */
  canManageFinance: boolean;
  /** Read the tenant-wide finance ledger (`can_view_tenant_finance`). */
  canViewTenantFinance: boolean;
  /** Create shipments and pickup requests (`assert_can_manage_shipments_or_pickups`). */
  canBook: boolean;
  /** Status updates, dispatch, OTP POD, raise NDR, weight audit, edit shipment. */
  canOperate: boolean;
  /** Reply to / resolve support tickets and assist with exceptions. */
  canHandleSupport: boolean;
  /** Any write at all (`assert_not_read_only`). */
  canWrite: boolean;
  /**
   * Has a wallet of their own that shipments are billed to (customers, and the
   * staff who can book: owner, admin, operations). Shows the header wallet pill.
   */
  hasOwnWallet: boolean;
  /** Add money to their own wallet (`assert_can_manage_finance_or_wallet`). */
  canRechargeWallet: boolean;
  /** Open the Wallet page: an own wallet or the tenant-wide ledger. */
  canViewWallet: boolean;
  /**
   * Read COD remittances and GST invoices / notes (`_finance_scope_user_id`):
   * customers see their own, owner / admin / read-only the whole tenant.
   */
  canViewFinanceDocuments: boolean;
}

/** Owner / Admin (`ADMIN_USER_ROLES`). */
const ADMIN_ROLES: readonly UserRole[] = [UserRole.OWNER, UserRole.ADMIN];

/** Finance viewers (`TENANT_FINANCE_VIEWER_ROLES`). */
const FINANCE_VIEWER_ROLES: readonly UserRole[] = [
  UserRole.OWNER,
  UserRole.ADMIN,
  UserRole.READ_ONLY_USER,
];

/** Roles allowed to book shipments and pickup requests. */
const BOOKING_ROLES: readonly UserRole[] = [
  UserRole.CUSTOMER,
  UserRole.OWNER,
  UserRole.ADMIN,
  UserRole.OPERATIONS_USER,
];

/** Roles that may recharge their own wallet (customers and Owner / Admin). */
const WALLET_RECHARGE_ROLES: readonly UserRole[] = [
  UserRole.CUSTOMER,
  UserRole.OWNER,
  UserRole.ADMIN,
];

/** Roles allowed to run carrier operations (status, dispatch, POD, NDR, audit). */
const OPERATIONS_ROLES: readonly UserRole[] = [
  UserRole.OWNER,
  UserRole.ADMIN,
  UserRole.OPERATIONS_USER,
];

/** Roles allowed to work the support desk. */
const SUPPORT_ROLES: readonly UserRole[] = [
  UserRole.OWNER,
  UserRole.ADMIN,
  UserRole.SUPPORT_USER,
  UserRole.OPERATIONS_USER,
];

/** Capabilities of a signed-out / not-yet-loaded user: nothing. */
export const NO_CAPABILITIES: Readonly<UserCapabilities> = Object.freeze({
  isStaff: false,
  canManageTeam: false,
  canManageSettings: false,
  canManageFinance: false,
  canViewTenantFinance: false,
  canBook: false,
  canOperate: false,
  canHandleSupport: false,
  canWrite: false,
  hasOwnWallet: false,
  canRechargeWallet: false,
  canViewWallet: false,
  canViewFinanceDocuments: false,
});

/** Capability names, handy for config objects such as the nav menu. */
export type CapabilityKey = keyof UserCapabilities;

/**
 * Checks whether `role` is in `allowed`.
 *
 * @param role - The user's role.
 * @param allowed - Roles granted the capability.
 * @returns True when the role is granted.
 */
function _hasRole(role: UserRole, allowed: readonly UserRole[]): boolean {
  return allowed.includes(role);
}

/**
 * Resolves the UI capability map for a role.
 *
 * @param role - The user's role, or null/undefined while the profile loads.
 * @returns One boolean per capability (all false for an unknown user).
 */
export function resolveCapabilities(role: UserRole | null | undefined): UserCapabilities {
  if (!role) return Object.assign({}, NO_CAPABILITIES);
  const isAdmin = _hasRole(role, ADMIN_ROLES);
  const isCustomer = role === UserRole.CUSTOMER;
  const canViewTenantFinance = _hasRole(role, FINANCE_VIEWER_ROLES);
  const canBook = _hasRole(role, BOOKING_ROLES);
  return {
    isStaff: !isCustomer,
    canManageTeam: isAdmin,
    canManageSettings: isAdmin,
    canManageFinance: isAdmin,
    canViewTenantFinance,
    canBook,
    canOperate: _hasRole(role, OPERATIONS_ROLES),
    canHandleSupport: _hasRole(role, SUPPORT_ROLES),
    canWrite: role !== UserRole.READ_ONLY_USER,
    hasOwnWallet: canBook,
    canRechargeWallet: _hasRole(role, WALLET_RECHARGE_ROLES),
    canViewWallet: canBook || canViewTenantFinance,
    canViewFinanceDocuments: isCustomer || canViewTenantFinance,
  };
}
