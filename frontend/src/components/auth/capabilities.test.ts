// frontend/src/components/auth/capabilities.test.ts
import { UserRole } from "@/api_client";
import { describe, expect, it } from "vitest";

import { NO_CAPABILITIES, resolveCapabilities, type UserCapabilities } from "./capabilities";

/** Expected map per role, written out in full so a rule change is a visible diff. */
const EXPECTED: Readonly<Record<UserRole, UserCapabilities>> = {
  [UserRole.OWNER]: {
    isStaff: true,
    canManageTeam: true,
    canManageSettings: true,
    canManageFinance: true,
    canViewTenantFinance: true,
    canBook: true,
    canOperate: true,
    canHandleSupport: true,
    canWrite: true,
    hasOwnWallet: true,
    canRechargeWallet: true,
    canViewWallet: true,
    canViewFinanceDocuments: true,
  },
  [UserRole.ADMIN]: {
    isStaff: true,
    canManageTeam: true,
    canManageSettings: true,
    canManageFinance: true,
    canViewTenantFinance: true,
    canBook: true,
    canOperate: true,
    canHandleSupport: true,
    canWrite: true,
    hasOwnWallet: true,
    canRechargeWallet: true,
    canViewWallet: true,
    canViewFinanceDocuments: true,
  },
  [UserRole.OPERATIONS_USER]: {
    isStaff: true,
    canManageTeam: false,
    canManageSettings: false,
    canManageFinance: false,
    canViewTenantFinance: false,
    canBook: true,
    canOperate: true,
    canHandleSupport: true,
    canWrite: true,
    hasOwnWallet: true,
    canRechargeWallet: false,
    canViewWallet: true,
    canViewFinanceDocuments: false,
  },
  [UserRole.SUPPORT_USER]: {
    isStaff: true,
    canManageTeam: false,
    canManageSettings: false,
    canManageFinance: false,
    canViewTenantFinance: false,
    canBook: false,
    canOperate: false,
    canHandleSupport: true,
    canWrite: true,
    hasOwnWallet: false,
    canRechargeWallet: false,
    canViewWallet: false,
    canViewFinanceDocuments: false,
  },
  [UserRole.READ_ONLY_USER]: {
    isStaff: true,
    canManageTeam: false,
    canManageSettings: false,
    canManageFinance: false,
    canViewTenantFinance: true,
    canBook: false,
    canOperate: false,
    canHandleSupport: false,
    canWrite: false,
    hasOwnWallet: false,
    canRechargeWallet: false,
    canViewWallet: true,
    canViewFinanceDocuments: true,
  },
  [UserRole.CUSTOMER]: {
    isStaff: false,
    canManageTeam: false,
    canManageSettings: false,
    canManageFinance: false,
    canViewTenantFinance: false,
    canBook: true,
    canOperate: false,
    canHandleSupport: false,
    canWrite: true,
    hasOwnWallet: true,
    canRechargeWallet: true,
    canViewWallet: true,
    canViewFinanceDocuments: true,
  },
};

describe("resolveCapabilities", () => {
  for (const role of Object.values(UserRole)) {
    it(`matches the backend rules for ${role}`, () => {
      expect(resolveCapabilities(role)).toEqual(EXPECTED[role]);
    });
  }

  it("grants nothing while the profile is unknown", () => {
    expect(resolveCapabilities(null)).toEqual(NO_CAPABILITIES);
    expect(resolveCapabilities(undefined)).toEqual(NO_CAPABILITIES);
  });

  it("returns a fresh object so callers cannot mutate the shared default", () => {
    const caps = resolveCapabilities(null);
    caps.canBook = true;
    expect(NO_CAPABILITIES.canBook).toBe(false);
  });
});
