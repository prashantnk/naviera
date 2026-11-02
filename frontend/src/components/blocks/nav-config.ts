// frontend/src/components/blocks/nav-config.ts
/**
 * Single source of truth for the authenticated app navigation.
 *
 * Both the desktop sidebar (`app-sidebar.tsx`) and the mobile drawer
 * (`app-header.tsx`) render this config through `NavMenu`, so the two menus
 * can never drift apart. The layout mirrors Delhivery One: a flat list of
 * top-level entries, some of which are expandable groups (Orders & Pickups ▸,
 * Finances ▸, Settings ▸). We list only features Naviera really has.
 *
 * Visibility per role comes from `capabilities.ts` (mirror of the backend
 * `permissions.py`): an item with a `capability` is hidden unless the user has
 * it, and a group with no visible children is hidden entirely.
 */
import {
  Banknote,
  Calculator,
  CalendarClock,
  Headset,
  House,
  PackageCheck,
  RadioTower,
  Scale,
  Settings,
  TriangleAlert,
  Truck,
  type LucideIcon,
} from "lucide-react";

import type { CapabilityKey, UserCapabilities } from "@/components/auth/capabilities";
import {
  B2B_CATEGORY_ORDER,
  EXCEPTION_CATEGORY_META,
} from "@/components/exceptions/exception-meta";
import { ServiceFlow } from "@/lib/workspace-flow";

/** Query parameter the exceptions workspace reads to pick its category. */
export const EXCEPTION_CATEGORY_QUERY_PARAM = "category";

/** Base route of the B2B Delivery Exceptions workspace. */
const B2B_EXCEPTIONS_HREF = "/b2b/delivery-exceptions";

/** A clickable menu entry (top-level link or group child). */
export interface NavLink {
  name: string;
  href: string;
  /** Extra tenant-relative paths that also mark this link active. */
  aliases?: readonly string[];
  /** Hidden unless the user has this capability. */
  capability?: CapabilityKey;
}

/** A top-level menu entry: either a link (`href`) or a group (`children`). */
export interface NavItem {
  name: string;
  icon: LucideIcon;
  href?: string;
  aliases?: readonly string[];
  capability?: CapabilityKey;
  children?: readonly NavLink[];
  /** Optional visual section header rendered above this item in the expanded sidebar. */
  sectionHeader?: string;
}

const PLATFORM_SETUP_HREFS: ReadonlySet<string> = new Set([
  "/team",
  "/settings",
  "/settings/prime-lanes",
]);

/**
 * Whether a Settings child link belongs to the Admin / Staff Platform Setup sub-group
 * rather than the everyday customer address book.
 *
 * @param link - Child link inside the Settings group.
 * @returns True for `/team`, `/settings`, and `/settings/prime-lanes`.
 */
export function isPlatformSetupLink(link: NavLink): boolean {
  return PLATFORM_SETUP_HREFS.has(link.href);
}

/**
 * Finances ▸ group, identical in both flows. Support users have no wallet and,
 * like operations users, no access to sellers' remittances or GST documents
 * (backend `_finance_scope_user_id` answers 403), so those entries are hidden.
 */
const FINANCES_GROUP: NavItem = {
  name: "Finances",
  icon: Banknote,
  children: [
    { name: "Wallet", href: "/wallet", capability: "canViewWallet" },
    { name: "Remittances", href: "/finances/remittances", capability: "canViewFinanceDocuments" },
    { name: "Invoices", href: "/finances/invoices", capability: "canViewFinanceDocuments" },
  ],
};

/** Support entry, identical in both flows. */
const SUPPORT_ITEM: NavItem = { name: "Support", icon: Headset, href: "/support" };

/**
 * Logismart's own operations screen (pickups, dispatch, delivery, NDR, weight
 * audit). Delhivery One has no equivalent because theirs is internal; decision
 * D25-bis keeps it in the menu for staff who operate parcels.
 */
const OPS_ITEM: NavItem = {
  name: "Ops Control Tower",
  icon: RadioTower,
  href: "/ops",
  capability: "canOperate",
  sectionHeader: "Staff & Hub Operations",
};

/**
 * Users + Workspace Settings (Owner / Admin only) and Pricing & Prime lanes
 * (any staff: read-only for non-admins, edits stay Owner / Admin on the page).
 */
const ADMIN_SETTINGS_CHILDREN: readonly NavLink[] = [
  { name: "Users", href: "/team", capability: "canManageTeam" },
  { name: "Workspace Settings", href: "/settings", capability: "canManageSettings" },
  { name: "Pricing & Prime lanes", href: "/settings/prime-lanes", capability: "isStaff" },
];

/**
 * Settings ▸ children: the address book (label differs per flow) plus the
 * Owner / Admin-only Users and Workspace Settings pages.
 *
 * @param addressBookLabel - "Pickup Addresses" (B2C) or "My Facilities" (B2B).
 * @returns Settings group children in display order.
 */
function _settingsChildren(addressBookLabel: string): readonly NavLink[] {
  const addressBook: NavLink = { name: addressBookLabel, href: "/address-book" };
  return [addressBook].concat(ADMIN_SETTINGS_CHILDREN);
}

/** One Delivery Exceptions child per B2B exception category (Delhivery Cargo order). */
const B2B_EXCEPTION_CHILDREN: readonly NavLink[] = B2B_CATEGORY_ORDER.map((category) => ({
  name: EXCEPTION_CATEGORY_META[category].label,
  href: `${B2B_EXCEPTIONS_HREF}?${EXCEPTION_CATEGORY_QUERY_PARAM}=${category}`,
}));

/** B2C (Domestic) menu, Delhivery One order. */
export const B2C_NAV: readonly NavItem[] = [
  { name: "Home", icon: House, href: "/dashboard" },
  {
    name: "Orders & Pickups",
    icon: PackageCheck,
    children: [
      { name: "Orders", href: "/shipments" },
      { name: "Pickup Requests", href: "/pickup-requests" },
    ],
  },
  { name: "Delivery Exceptions", icon: TriangleAlert, href: "/delivery-exceptions" },
  FINANCES_GROUP,
  SUPPORT_ITEM,
  {
    name: "Disputes",
    icon: Scale,
    children: [{ name: "Weight Mismatch", href: "/disputes/weight-mismatch" }],
  },
  { name: "Rate calculator & serviceability", icon: Calculator, href: "/rate-calculator" },
  {
    name: "Settings",
    icon: Settings,
    children: _settingsChildren("Pickup Addresses"),
  },
  OPS_ITEM,
];

/** B2B (Cargo) menu, Delhivery One order. */
export const B2B_NAV: readonly NavItem[] = [
  { name: "Home", icon: House, href: "/b2b/dashboard", aliases: ["/b2b"] },
  { name: "B2B Orders", icon: PackageCheck, href: "/b2b/shipments" },
  { name: "Pickup Requests", icon: Truck, href: "/b2b/pickup-requests" },
  { name: "Manage Appointments", icon: CalendarClock, href: "/b2b/appointments" },
  { name: "Delivery Exceptions", icon: TriangleAlert, children: B2B_EXCEPTION_CHILDREN },
  FINANCES_GROUP,
  SUPPORT_ITEM,
  { name: "Disputes", icon: Scale, href: "/disputes/weight-mismatch" },
  { name: "Rate calculator & serviceability", icon: Calculator, href: "/b2b/rate-calculator" },
  {
    name: "Settings",
    icon: Settings,
    children: _settingsChildren("My Facilities"),
  },
  OPS_ITEM,
];

/**
 * Whether the user may see an entry with an optional capability requirement.
 *
 * @param capability - Required capability, if any.
 * @param capabilities - The user's capability map.
 * @returns True when no capability is required or the user has it.
 */
function _isAllowed(
  capability: CapabilityKey | undefined,
  capabilities: UserCapabilities
): boolean {
  return capability === undefined || capabilities[capability];
}

/**
 * Filters one menu entry for the user, dropping hidden children and empty groups.
 *
 * @param item - Menu entry from the static config.
 * @param capabilities - The user's capability map.
 * @returns The visible entry, or null when nothing in it is visible.
 */
function _filterItem(item: NavItem, capabilities: UserCapabilities): NavItem | null {
  if (!_isAllowed(item.capability, capabilities)) return null;
  if (!item.children) return item;
  const children = item.children.filter((child) =>
    _isAllowed(child.capability, capabilities)
  );
  if (children.length === 0) return null;
  return Object.assign({}, item, { children });
}

/**
 * Returns the menu for a flow, filtered to what the user is allowed to see.
 *
 * @param flow - The active business flow.
 * @param capabilities - The user's capability map.
 * @returns Visible top-level entries in display order.
 */
export function getNavItems(
  flow: ServiceFlow,
  capabilities: UserCapabilities
): NavItem[] {
  const config = flow === ServiceFlow.B2B ? B2B_NAV : B2C_NAV;
  return config
    .map((item) => _filterItem(item, capabilities))
    .filter((item): item is NavItem => item !== null);
}

/**
 * Splits an href into its path and optional `category` query value.
 *
 * @param href - Tenant-relative href, possibly with a query string.
 * @returns Path plus the category value (null when absent).
 */
function _splitHref(href: string): { path: string; category: string | null } {
  const [path, query] = href.split("?");
  const category = query ? new URLSearchParams(query).get(EXCEPTION_CATEGORY_QUERY_PARAM) : null;
  return { path, category };
}

/**
 * Checks whether `path` is `base` or nested beneath it.
 *
 * @param path - Current tenant-relative path.
 * @param base - Menu href path.
 * @returns True on exact or nested match.
 */
function _isSameOrNested(path: string, base: string): boolean {
  return path === base || path.startsWith(`${base}/`);
}

/**
 * Whether a link is the active one for the current location.
 *
 * Nested pages (e.g. `/shipments/123`, `/finances/invoices/abc`) keep their
 * parent link active. Links that carry a `category` query (B2B exception
 * categories) are active only when the URL category matches; with no category
 * in the URL the first category of the group is the workspace default.
 *
 * @param link - Menu link.
 * @param relativePath - Current tenant-relative pathname.
 * @param currentCategory - Current `category` query value (null when absent).
 * @param isDefaultCategory - Whether this link is its group's default category.
 * @returns True when the link should render as active.
 */
export function isNavLinkActive(
  link: NavLink,
  relativePath: string,
  currentCategory: string | null,
  isDefaultCategory = false
): boolean {
  const { path, category } = _splitHref(link.href);
  const pathMatches =
    _isSameOrNested(relativePath, path) ||
    (link.aliases ?? []).some((alias) => relativePath === alias);
  if (!pathMatches) return false;
  if (category === null) return true;
  return currentCategory ? currentCategory === category : isDefaultCategory;
}

/**
 * Whether any child of a group is active (used to auto-expand the group).
 *
 * @param item - Top-level menu entry.
 * @param relativePath - Current tenant-relative pathname.
 * @param currentCategory - Current `category` query value.
 * @returns True when the entry itself or one of its children is active.
 */
export function isNavItemActive(
  item: NavItem,
  relativePath: string,
  currentCategory: string | null
): boolean {
  if (item.children) {
    return item.children.some((child, index) =>
      isNavLinkActive(child, relativePath, currentCategory, index === 0)
    );
  }
  if (!item.href) return false;
  return isNavLinkActive(
    { name: item.name, href: item.href, aliases: item.aliases },
    relativePath,
    currentCategory
  );
}
