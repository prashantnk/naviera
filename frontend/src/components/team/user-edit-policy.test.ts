import { describe, expect, it } from "vitest";

import { UserRole } from "@/api_client";

import {
  ADMIN_GRANT_REASON,
  ADMIN_LOCK_REASON,
  formatUserPhone,
  getUserEditPolicy,
  isOwnershipTransfer,
  OWNER_LOCK_REASON,
  SELF_LOCK_REASON,
  sortUsersForTable,
} from "./user-edit-policy";

const owner = { id: "o", role: UserRole.OWNER };
const admin = { id: "a", role: UserRole.ADMIN };
const ops = { id: "p", role: UserRole.OPERATIONS_USER };
const customer = { id: "c", role: UserRole.CUSTOMER };

describe("getUserEditPolicy", () => {
  it("locks everything for yourself", () => {
    const policy = getUserEditPolicy(admin, admin);
    expect(policy.roleLocked).toBe(true);
    expect(policy.statusLocked).toBe(true);
    expect(policy.lockReason).toBe(SELF_LOCK_REASON);
  });

  it("never lets anyone demote or deactivate the Owner", () => {
    const policy = getUserEditPolicy(admin, owner);
    expect(policy.roleLocked).toBe(true);
    expect(policy.statusLocked).toBe(true);
    expect(policy.lockReason).toBe(OWNER_LOCK_REASON);
  });

  it("stops an Admin from changing another Admin", () => {
    const policy = getUserEditPolicy(admin, { id: "a2", role: UserRole.ADMIN });
    expect(policy.roleLocked).toBe(true);
    expect(policy.lockReason).toBe(ADMIN_LOCK_REASON);
  });

  it("lets an Admin change staff and customers but not grant Owner/Admin", () => {
    const policy = getUserEditPolicy(admin, customer);
    expect(policy.roleLocked).toBe(false);
    expect(policy.statusLocked).toBe(false);
    expect(policy.disabledRoles.has(UserRole.OWNER)).toBe(true);
    expect(policy.disabledRoles.has(UserRole.ADMIN)).toBe(true);
    expect(policy.disabledRoles.has(UserRole.SUPPORT_USER)).toBe(false);
    expect(policy.lockReason).toBe(ADMIN_GRANT_REASON);
  });

  it("lets the Owner grant any role, including Admin and Owner", () => {
    const policy = getUserEditPolicy(owner, admin);
    expect(policy.roleLocked).toBe(false);
    expect(policy.disabledRoles.size).toBe(0);
    expect(policy.lockReason).toBeNull();
  });

  it("offers the B2C/B2B scope menu for customers only", () => {
    expect(getUserEditPolicy(owner, customer).canChangeScope).toBe(true);
    expect(getUserEditPolicy(owner, ops).canChangeScope).toBe(false);
  });

  it("locks everything while the signed-in profile is unknown", () => {
    expect(getUserEditPolicy(null, customer).roleLocked).toBe(true);
  });
});

describe("isOwnershipTransfer", () => {
  it("is true only when a non-owner is made Owner", () => {
    expect(isOwnershipTransfer(admin, UserRole.OWNER)).toBe(true);
    expect(isOwnershipTransfer(owner, UserRole.OWNER)).toBe(false);
    expect(isOwnershipTransfer(admin, UserRole.ADMIN)).toBe(false);
  });
});

describe("sortUsersForTable", () => {
  it("puts the team first in role order, customers last, then by email", () => {
    const sorted = sortUsersForTable([
      { id: "1", role: UserRole.CUSTOMER, email: "b@x.in" },
      { id: "2", role: UserRole.SUPPORT_USER, email: "s@x.in" },
      { id: "3", role: UserRole.CUSTOMER, email: "a@x.in" },
      { id: "4", role: UserRole.OWNER, email: "z@x.in" },
    ]);
    expect(sorted.map((u) => u.id)).toEqual(["4", "2", "3", "1"]);
  });
});

describe("formatUserPhone", () => {
  it("adds +91 only to numbers stored without a country code", () => {
    expect(formatUserPhone("9876543210")).toBe("+91 9876543210");
    expect(formatUserPhone("+919876543210")).toBe("+919876543210");
  });
});
