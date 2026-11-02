// frontend/src/components/blocks/nav-config.test.ts
import { ExceptionCategory, UserRole } from "@/api_client";
import { resolveCapabilities } from "@/components/auth/capabilities";
import { B2B_CATEGORY_ORDER } from "@/components/exceptions/exception-meta";
import { ServiceFlow } from "@/lib/workspace-flow";
import { describe, expect, it } from "vitest";

import {
  getNavItems,
  isNavItemActive,
  isNavLinkActive,
  isPlatformSetupLink,
  type NavItem,
} from "./nav-config";

/** Top-level labels of the visible menu. */
function topLevel(items: NavItem[]): string[] {
  return items.map((item) => item.name);
}

/** Child labels of a named group (empty when the group is hidden). */
function childrenOf(items: NavItem[], groupName: string): string[] {
  const group = items.find((item) => item.name === groupName);
  return (group?.children ?? []).map((child) => child.name);
}

/** Every href in the visible menu, including group children. */
function allHrefs(items: NavItem[]): string[] {
  const hrefs: string[] = [];
  for (const item of items) {
    if (item.href) hrefs.push(item.href);
    for (const child of item.children ?? []) hrefs.push(child.href);
  }
  return hrefs;
}

const B2C_TOP_LEVEL = [
  "Home",
  "Orders & Pickups",
  "Delivery Exceptions",
  "Finances",
  "Support",
  "Disputes",
  "Rate calculator & serviceability",
  "Settings",
  "Ops Control Tower",
];

const B2B_TOP_LEVEL = [
  "Home",
  "B2B Orders",
  "Pickup Requests",
  "Manage Appointments",
  "Delivery Exceptions",
  "Finances",
  "Support",
  "Disputes",
  "Rate calculator & serviceability",
  "Settings",
  "Ops Control Tower",
];

const ADMIN_ROLES = [UserRole.OWNER, UserRole.ADMIN];
const NON_ADMIN_ROLES = [
  UserRole.OPERATIONS_USER,
  UserRole.SUPPORT_USER,
  UserRole.READ_ONLY_USER,
  UserRole.CUSTOMER,
];

describe("getNavItems — Delhivery layout", () => {
  it("B2C menu has the Delhivery order and groups", () => {
    const items = getNavItems(ServiceFlow.B2C, resolveCapabilities(UserRole.OWNER));
    expect(topLevel(items)).toEqual(B2C_TOP_LEVEL);
    expect(childrenOf(items, "Orders & Pickups")).toEqual(["Orders", "Pickup Requests"]);
    expect(childrenOf(items, "Finances")).toEqual(["Wallet", "Remittances", "Invoices"]);
    expect(childrenOf(items, "Disputes")).toEqual(["Weight Mismatch"]);
    expect(childrenOf(items, "Settings")).toEqual([
      "Pickup Addresses",
      "Users",
      "Workspace Settings",
      "Pricing & Prime lanes",
    ]);
  });

  it("B2B menu has the Delhivery order, one exception child per category, and My Facilities", () => {
    const items = getNavItems(ServiceFlow.B2B, resolveCapabilities(UserRole.OWNER));
    expect(topLevel(items)).toEqual(B2B_TOP_LEVEL);
    expect(childrenOf(items, "Delivery Exceptions")).toHaveLength(B2B_CATEGORY_ORDER.length);
    expect(childrenOf(items, "Settings")).toEqual([
      "My Facilities",
      "Users",
      "Workspace Settings",
      "Pricing & Prime lanes",
    ]);
    const exceptionHrefs = (items.find((i) => i.name === "Delivery Exceptions")?.children ?? []).map(
      (child) => child.href
    );
    expect(exceptionHrefs[0]).toBe(
      `/b2b/delivery-exceptions?category=${B2B_CATEGORY_ORDER[0]}`
    );
  });

  it("never shows booking shortcuts or unsupported features", () => {
    for (const flow of [ServiceFlow.B2C, ServiceFlow.B2B]) {
      const items = getNavItems(flow, resolveCapabilities(UserRole.OWNER));
      const labels = topLevel(items).concat(items.flatMap((i) => (i.children ?? []).map((c) => c.name)));
      for (const hidden of [
        "Forward Shipment",
        "Reverse Shipment",
        "Book Forward Cargo",
        "B2B Return / Pickup",
        "Direct Intracity Orders",
        "Reports",
        "Information Center",
        "Services",
        "Bank Details",
        "Manage Documents",
      ]) {
        expect(labels).not.toContain(hidden);
      }
      expect(allHrefs(items).some((href) => href.includes("/new/"))).toBe(false);
    }
  });

  it("shows the Ops Control Tower only to roles that operate parcels (D25-bis)", () => {
    const operators = [UserRole.OWNER, UserRole.ADMIN, UserRole.OPERATIONS_USER];
    const others = [UserRole.SUPPORT_USER, UserRole.READ_ONLY_USER, UserRole.CUSTOMER];
    for (const flow of [ServiceFlow.B2C, ServiceFlow.B2B]) {
      for (const role of operators) {
        const items = getNavItems(flow, resolveCapabilities(role));
        expect(allHrefs(items)).toContain("/ops");
        const opsItem = items.find((i) => i.href === "/ops");
        expect(opsItem?.sectionHeader).toBe("Staff & Hub Operations");
      }
      for (const role of others) {
        expect(allHrefs(getNavItems(flow, resolveCapabilities(role)))).not.toContain("/ops");
      }
    }
  });

  it("marks admin/staff Settings children as Platform Setup links while keeping address book in Daily Shipping", () => {
    const items = getNavItems(ServiceFlow.B2C, resolveCapabilities(UserRole.OWNER));
    const settingsChildren = items.find((i) => i.name === "Settings")?.children ?? [];
    expect(settingsChildren.map((c) => isPlatformSetupLink(c))).toEqual([
      false, // Pickup Addresses
      true,  // Users
      true,  // Workspace Settings
      true,  // Pricing & Prime lanes
    ]);
  });
});

describe("getNavItems — role visibility", () => {
  for (const role of ADMIN_ROLES) {
    it(`${role} sees Users and Workspace Settings in both flows`, () => {
      for (const flow of [ServiceFlow.B2C, ServiceFlow.B2B]) {
        const hrefs = allHrefs(getNavItems(flow, resolveCapabilities(role)));
        expect(hrefs).toContain("/team");
        expect(hrefs).toContain("/settings");
        expect(hrefs).toContain("/address-book");
      }
    });
  }

  for (const role of NON_ADMIN_ROLES) {
    it(`${role} does not see Users or Workspace Settings but keeps the address book`, () => {
      for (const flow of [ServiceFlow.B2C, ServiceFlow.B2B]) {
        const items = getNavItems(flow, resolveCapabilities(role));
        const hrefs = allHrefs(items);
        expect(hrefs).not.toContain("/team");
        expect(hrefs).not.toContain("/settings");
        expect(hrefs).toContain("/address-book");
        expect(topLevel(items)).toContain("Settings");
        // Pricing & Prime lanes is staff-only (read-only for non-admin staff).
        expect(hrefs.includes("/settings/prime-lanes")).toBe(resolveCapabilities(role).isStaff);
      }
    });
  }

  it("a user with no profile yet still gets the everyone-visible menu", () => {
    const items = getNavItems(ServiceFlow.B2C, resolveCapabilities(null));
    expect(topLevel(items)).toEqual(
      B2C_TOP_LEVEL.filter((name) => name !== "Ops Control Tower" && name !== "Finances")
    );
    expect(childrenOf(items, "Settings")).toEqual(["Pickup Addresses"]);
  });

  it("shows Finances entries only where the finance API answers (no 403 pages)", () => {
    const expected: Record<UserRole, string[]> = {
      [UserRole.OWNER]: ["Wallet", "Remittances", "Invoices"],
      [UserRole.ADMIN]: ["Wallet", "Remittances", "Invoices"],
      [UserRole.READ_ONLY_USER]: ["Wallet", "Remittances", "Invoices"],
      [UserRole.CUSTOMER]: ["Wallet", "Remittances", "Invoices"],
      // Operations users keep their own (booking) wallet but not sellers' payouts / GST docs.
      [UserRole.OPERATIONS_USER]: ["Wallet"],
      // Support users have no wallet and no finance access: the whole group is hidden.
      [UserRole.SUPPORT_USER]: [],
    };
    for (const flow of [ServiceFlow.B2C, ServiceFlow.B2B]) {
      for (const role of Object.values(UserRole)) {
        const items = getNavItems(flow, resolveCapabilities(role));
        expect(childrenOf(items, "Finances")).toEqual(expected[role]);
      }
    }
  });
});

describe("active state", () => {
  const b2cItems = getNavItems(ServiceFlow.B2C, resolveCapabilities(UserRole.CUSTOMER));
  const b2bItems = getNavItems(ServiceFlow.B2B, resolveCapabilities(UserRole.CUSTOMER));
  const byName = (items: NavItem[], name: string) => items.find((i) => i.name === name) as NavItem;

  it("keeps Orders active on nested order and create pages", () => {
    const orders = byName(b2cItems, "Orders & Pickups");
    expect(isNavItemActive(orders, "/shipments", null)).toBe(true);
    expect(isNavItemActive(orders, "/shipments/abc", null)).toBe(true);
    expect(isNavItemActive(orders, "/shipments/new/forward", null)).toBe(true);
    expect(isNavItemActive(orders, "/pickup-requests/new", null)).toBe(true);
    expect(isNavItemActive(orders, "/shipmentsx", null)).toBe(false);
  });

  it("marks Finances active on detail pages", () => {
    expect(isNavItemActive(byName(b2cItems, "Finances"), "/finances/invoices/123", null)).toBe(true);
  });

  it("treats /b2b as the B2B Home alias", () => {
    expect(isNavItemActive(byName(b2bItems, "Home"), "/b2b", null)).toBe(true);
    expect(isNavItemActive(byName(b2bItems, "Home"), "/b2b/shipments", null)).toBe(false);
  });

  it("matches B2B exception children by category, defaulting to the first", () => {
    const group = byName(b2bItems, "Delivery Exceptions");
    const children = group.children ?? [];
    const first = children[0];
    const appointment = children.find((c) =>
      c.href.endsWith(ExceptionCategory.APPOINTMENT_NEEDED)
    );
    expect(appointment).toBeDefined();
    expect(isNavLinkActive(first, "/b2b/delivery-exceptions", null, true)).toBe(true);
    expect(
      isNavLinkActive(first, "/b2b/delivery-exceptions", ExceptionCategory.APPOINTMENT_NEEDED, true)
    ).toBe(false);
    expect(
      isNavLinkActive(
        appointment!,
        "/b2b/delivery-exceptions",
        ExceptionCategory.APPOINTMENT_NEEDED
      )
    ).toBe(true);
    expect(isNavItemActive(group, "/b2b/delivery-exceptions", null)).toBe(true);
    expect(isNavItemActive(group, "/b2b/shipments", null)).toBe(false);
  });
});
