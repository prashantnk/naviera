// frontend/src/components/blocks/nav-menu.tsx
"use client";

/**
 * Renders the grouped app navigation (`nav-config.ts`) for both the desktop
 * sidebar and the mobile drawer, Delhivery One style: dark rail, icon + label,
 * expandable groups with a chevron, active group auto-expanded.
 */
import { useUser } from "@/components/auth/auth-guard";
import {
  EXCEPTION_CATEGORY_QUERY_PARAM,
  getNavItems,
  isNavItemActive,
  isNavLinkActive,
  isPlatformSetupLink,
  type NavItem,
} from "@/components/blocks/nav-config";
import { useTenant } from "@/components/providers/tenant-provider";
import { useWorkspaceFlow } from "@/components/providers/workspace-flow-provider";
import { cn } from "@/lib/utils";
import { toTenantRelativePath } from "@/lib/workspace-flow";
import { ChevronRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

/** Shared row classes for top-level entries. */
const ROW_BASE_CLASS =
  "flex w-full items-center rounded-xl font-medium transition-colors whitespace-nowrap";
const ROW_IDLE_CLASS = "text-slate-300 hover:bg-slate-800/60 hover:text-white";
const ROW_ACTIVE_LINK_CLASS = "bg-primary text-primary-foreground shadow-sm";
const ROW_ACTIVE_GROUP_CLASS = "bg-slate-800/70 text-white";

interface NavMenuProps {
  /** Whether labels are visible (false = collapsed icon rail). */
  isExpanded: boolean;
  /** Called after a link is clicked (e.g. close the mobile drawer). */
  onNavigate?: () => void;
}

function _splitNavTarget(href: string): { path: string; category: string | null } {
  const [path, query] = href.split("?");
  const category = query
    ? new URLSearchParams(query).get(EXCEPTION_CATEGORY_QUERY_PARAM)
    : null;
  return { path: path || "/", category };
}

function NavMenuContent({ isExpanded, onNavigate }: NavMenuProps) {
  const { routeTo, tenantSlug } = useTenant();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { capabilities } = useUser();
  const { activeFlow } = useWorkspaceFlow();

  // Explicit open/closed choice per group; groups without a choice follow the route.
  const [groupOverrides, setGroupOverrides] = useState<Record<string, boolean>>({});

  const actualRelativePath = toTenantRelativePath(pathname || "/", tenantSlug);
  const actualCategory = searchParams.get(EXCEPTION_CATEGORY_QUERY_PARAM);
  const locationKey = `${actualRelativePath}?${actualCategory || ""}`;

  // Optimistic navigation state: highlights the clicked nav item in <16ms while
  // Next.js transitions to the new route, and auto-clears once locationKey updates.
  const [optimisticNav, setOptimisticNav] = useState<{
    href: string;
    fromKey: string;
  } | null>(null);

  const pendingHref =
    optimisticNav && optimisticNav.fromKey === locationKey
      ? optimisticNav.href
      : null;
  const pendingTarget = pendingHref ? _splitNavTarget(pendingHref) : null;
  const relativePath = pendingTarget ? pendingTarget.path : actualRelativePath;
  const currentCategory = pendingTarget ? pendingTarget.category : actualCategory;

  const items = getNavItems(activeFlow, capabilities);

  // Eagerly prefetch all visible sidebar routes so clicking any menu item is instant.
  useEffect(() => {
    if (typeof router?.prefetch !== "function") return;
    const timer = setTimeout(() => {
      for (const item of items) {
        if (item.href) {
          router.prefetch(routeTo(item.href));
        }
        for (const child of item.children ?? []) {
          router.prefetch(routeTo(child.href));
        }
      }
    }, 30);
    return () => clearTimeout(timer);
  }, [items, routeTo, router]);

  const handleLinkClick = (targetHref: string) => {
    const target = _splitNavTarget(targetHref);
    if (
      target.path !== actualRelativePath ||
      (target.category ?? null) !== (actualCategory ?? null)
    ) {
      setOptimisticNav({ href: targetHref, fromKey: locationKey });
    }
    onNavigate?.();
  };

  const toggleGroup = (name: string, isOpen: boolean) => {
    setGroupOverrides((prev) => Object.assign({}, prev, { [name]: !isOpen }));
  };

  const renderLeaf = (item: NavItem) => {
    const targetHref = item.href || "/";
    const isActive = isNavItemActive(item, relativePath, currentCategory);
    const isPending = pendingHref === targetHref;
    return (
      <div key={item.name}>
        {isExpanded && item.sectionHeader && (
          <div
            data-testid="nav.section.staff-ops"
            className="mt-3 mb-1 border-t border-slate-800/80 pt-2.5 px-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-500"
          >
            {item.sectionHeader}
          </div>
        )}
        <Link
          href={routeTo(targetHref)}
          prefetch={true}
          onClick={() => handleLinkClick(targetHref)}
          title={!isExpanded ? item.name : undefined}
          aria-current={isActive ? "page" : undefined}
          data-pending={isPending ? "true" : undefined}
          className={cn(
            ROW_BASE_CLASS,
            isExpanded ? "gap-3 px-3 py-2 text-sm" : "justify-center h-9 w-9 mx-auto",
            isActive ? ROW_ACTIVE_LINK_CLASS : ROW_IDLE_CLASS
          )}
        >
          {isPending && !isExpanded ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
          ) : (
            <item.icon className="h-4 w-4 shrink-0" />
          )}
          {isExpanded && (
            <>
              <span className="flex-1 truncate whitespace-normal leading-tight">{item.name}</span>
              {isPending && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin opacity-80" />}
            </>
          )}
        </Link>
      </div>
    );
  };

  const renderGroup = (item: NavItem) => {
    const children = item.children ?? [];
    const isActive = isNavItemActive(item, relativePath, currentCategory);
    const isOpen = groupOverrides[item.name] ?? isActive;
    const showChildren = isExpanded && isOpen;
    const firstPlatformSetupIndex = children.findIndex((c) => isPlatformSetupLink(c));
    return (
      <div key={item.name}>
        <button
          type="button"
          onClick={() => toggleGroup(item.name, isOpen)}
          title={!isExpanded ? item.name : undefined}
          aria-expanded={isOpen}
          className={cn(
            ROW_BASE_CLASS,
            isExpanded ? "gap-3 px-3 py-2 text-sm text-left" : "justify-center h-9 w-9 mx-auto",
            isActive ? ROW_ACTIVE_GROUP_CLASS : ROW_IDLE_CLASS
          )}
        >
          <item.icon className="h-4 w-4 shrink-0" />
          {isExpanded && (
            <>
              <span className="flex-1 truncate">{item.name}</span>
              <ChevronRight
                className={cn(
                  "h-4 w-4 shrink-0 transition-transform duration-200",
                  isOpen && "rotate-90"
                )}
              />
            </>
          )}
        </button>
        {showChildren && (
          <div className="mt-0.5 mb-1 space-y-0.5">
            {children.map((child, index) => {
              const childActive = isNavLinkActive(
                child,
                relativePath,
                currentCategory,
                index === 0
              );
              const isChildPending = pendingHref === child.href;
              const showPlatformSetupHeader =
                firstPlatformSetupIndex > 0 && index === firstPlatformSetupIndex;
              return (
                <div key={child.href}>
                  {showPlatformSetupHeader && (
                    <div
                      data-testid="nav.section.platform-setup"
                      className="mt-2 mb-0.5 pl-10 pr-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-500"
                    >
                      Platform Setup
                    </div>
                  )}
                  <Link
                    href={routeTo(child.href)}
                    prefetch={true}
                    onClick={() => handleLinkClick(child.href)}
                    aria-current={childActive ? "page" : undefined}
                    data-pending={isChildPending ? "true" : undefined}
                    className={cn(
                      "flex items-center justify-between gap-2 rounded-lg py-1.5 pl-10 pr-3 text-[13px] transition-colors truncate",
                      childActive
                        ? "bg-primary text-primary-foreground font-semibold shadow-sm"
                        : "text-slate-400 hover:bg-slate-800/60 hover:text-white"
                    )}
                  >
                    <span className="truncate">{child.name}</span>
                    {isChildPending && (
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin opacity-80" />
                    )}
                  </Link>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-1">
      {isExpanded && capabilities.isStaff && (
        <div
          data-testid="nav.section.daily-shipping"
          className="px-3 pb-1 text-[10px] font-extrabold uppercase tracking-wider text-slate-500"
        >
          Daily Shipping &amp; Money
        </div>
      )}
      {items.map((item) => (item.children ? renderGroup(item) : renderLeaf(item)))}
    </div>
  );
}

/** `useSearchParams` (exception category deep links) must render inside `<Suspense>`. */
export function NavMenu(props: NavMenuProps) {
  return (
    <Suspense fallback={null}>
      <NavMenuContent isExpanded={props.isExpanded} onNavigate={props.onNavigate} />
    </Suspense>
  );
}
