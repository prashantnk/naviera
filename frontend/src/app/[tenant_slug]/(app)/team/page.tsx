// frontend/src/app/[tenant_slug]/(app)/team/page.tsx
"use client";

import {
  ServiceScope,
  UserRead,
  UserRole,
  UsersService,
  UserUpdate,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  formatUserPhone,
  getUserEditPolicy,
  isOwnershipTransfer,
  sortUsersForTable,
} from "@/components/team/user-edit-policy";
import { getInitials } from "@/lib/initials";
import {
  buildQueryCacheKey,
  getCachedQuery,
  hasCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { extractApiErrorMessage, formatIstDate } from "@/lib/utils";
import {
  Building2,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  HelpCircle,
  Layers,
  Loader2,
  MoreHorizontal,
  Package,
  Pencil,
  Search,
  ShieldAlert,
  Truck,
  UserCheck,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

interface RoleDefinition {
  key: UserRole;
  label: string;
  capabilities: readonly string[];
}

export const USER_ROLES: readonly RoleDefinition[] = [
  {
    key: UserRole.OWNER,
    label: "Owner",
    capabilities: [
      "View tenant-wide B2C & B2B dashboards and operational queues",
      "Create, edit, dispatch, and download shipments, manifests, and pickup requests",
      "Act on NDR / delivery exceptions and resolve weight mismatch disputes",
      "View, reply to, and manage all support tickets",
      "Manage tenant wallet recharges, COD remittances, and GST invoices / credit & debit notes",
      "Configure tenant settings, branding, pricing policy, Prime lanes, and company/bank details",
      "Promote or modify Admins and manage all team roles & B2B access requests",
    ],
  },
  {
    key: UserRole.ADMIN,
    label: "Admin",
    capabilities: [
      "View tenant-wide B2C & B2B dashboards and operational queues",
      "Create, edit, dispatch, and download shipments, manifests, and pickup requests",
      "Act on NDR / delivery exceptions and resolve weight mismatch disputes",
      "View, reply to, and manage all support tickets",
      "Manage tenant wallet recharges, COD remittances, and GST invoices / credit & debit notes",
      "Configure tenant settings, branding, pricing policy, and Prime lanes",
      "Manage Operations, Support, Read-Only, and Customer users (Owner required to promote/modify Admins)",
    ],
  },
  {
    key: UserRole.OPERATIONS_USER,
    label: "Operations-User",
    capabilities: [
      "View tenant-wide B2C & B2B dashboards, shipments, and tracking",
      "Create and dispatch pickup requests (manifests) and update shipment operational statuses",
      "Act on NDR / delivery exceptions and manage B2B appointments",
      "View weight mismatch disputes and warehouse pickup locations",
      "No access to tenant wallet, COD remittances, GST invoices, or team/settings administration",
    ],
  },
  {
    key: UserRole.SUPPORT_USER,
    label: "Support-User",
    capabilities: [
      "View tenant-wide B2C & B2B dashboards, shipments, and tracking",
      "View, reply to, resolve, and close customer support tickets",
      "Act on NDR / delivery exceptions on behalf of shippers",
      "View weight mismatch disputes and shipment activity history",
      "No access to tenant wallet, COD remittances, GST invoices, manifest dispatch, or team/settings administration",
    ],
  },
  {
    key: UserRole.READ_ONLY_USER,
    label: "Read access Only-User",
    capabilities: [
      "Tenant-wide read-only auditor across B2C & B2B dashboards, shipments, and manifests",
      "View all tenant wallet transactions, GST invoices, and COD remittances (read-only)",
      "View all support tickets, weight mismatch disputes, and NDR exceptions (read-only)",
      "Strict write block on all mutations (cannot book, edit, dispatch, recharge, or change settings/team)",
    ],
  },
  {
    key: UserRole.CUSTOMER,
    label: "Customer",
    capabilities: [
      "Default role assigned on signup (self-service shipper account)",
      "Book and manage their own B2C / B2B orders and pickup requests",
      "Act on their own NDR and delivery exceptions",
      "Recharge their own Unified Wallet and view their own GST invoices & COD remittances",
      "Raise weight mismatch claims and support tickets for their own shipments",
    ],
  },
];

const ROLE_LABEL_BY_KEY: Readonly<Record<UserRole, string>> = {
  [UserRole.OWNER]: "Owner",
  [UserRole.ADMIN]: "Admin",
  [UserRole.OPERATIONS_USER]: "Operations-User",
  [UserRole.SUPPORT_USER]: "Support-User",
  [UserRole.READ_ONLY_USER]: "Read access Only-User",
  [UserRole.CUSTOMER]: "Customer",
};

const SERVICE_SCOPE_CHOICES: readonly { value: ServiceScope; label: string }[] = [
  { value: ServiceScope.B2C, label: "B2C Express" },
  { value: ServiceScope.B2B, label: "B2B Heavy Cargo" },
  { value: ServiceScope.BOTH, label: "Unified (B2C & B2B)" },
];

function _resolveUserRole(user: UserRead): UserRole {
  if (
    user.role === UserRole.OWNER ||
    user.role === UserRole.ADMIN ||
    user.role === UserRole.OPERATIONS_USER ||
    user.role === UserRole.SUPPORT_USER ||
    user.role === UserRole.READ_ONLY_USER ||
    user.role === UserRole.CUSTOMER
  ) {
    return user.role;
  }
  return UserRole.CUSTOMER;
}

function _formatCreatedDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return formatIstDate(
    iso,
    {
      day: "2-digit",
      month: "short",
      year: "numeric",
    },
    iso
  );
}

function _renderScopePill(scope: ServiceScope | undefined) {
  const resolved = scope || ServiceScope.B2C;
  if (resolved === ServiceScope.B2B) {
    return (
      <Badge
        variant="outline"
        className="bg-amber-50 text-amber-700 border-amber-200 font-bold text-[10px] tracking-wider"
      >
        B2B
      </Badge>
    );
  }
  if (resolved === ServiceScope.BOTH) {
    return (
      <Badge
        variant="outline"
        className="bg-emerald-50 text-emerald-700 border-emerald-200 font-bold text-[10px] tracking-wider"
      >
        BOTH
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="bg-sky-50 text-sky-700 border-sky-200 font-bold text-[10px] tracking-wider"
    >
      B2C
    </Badge>
  );
}

export default function TeamManagementPage() {
  const { tenantSlug } = useTenant();
  const { canManageTeam, user: currentUser } = useUser();
  const cacheKey = buildQueryCacheKey(tenantSlug, "session", "tenant-users");
  const [users, setUsers] = useState<UserRead[]>(
    () => getCachedQuery<UserRead[]>(cacheKey) ?? []
  );
  const [loading, setLoading] = useState(
    () => !hasCachedQuery(cacheKey)
  );
  const [rolesHelpOpen, setRolesHelpOpen] = useState(false);

  // Filter Bar State
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [roleFilter, setRoleFilter] = useState("ALL");

  // Edit User Modal State (people sign up themselves; Owner/Admin promote them here)
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserRead | null>(null);

  const [fullNameInput, setFullNameInput] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [phoneInput, setPhoneInput] = useState("");
  const [companyNameInput, setCompanyNameInput] = useState("");
  const [gstinInput, setGstinInput] = useState("");
  const [panInput, setPanInput] = useState("");
  const [isActiveInput, setIsActiveInput] = useState(true);
  const [scopeInput, setScopeInput] = useState<ServiceScope>(ServiceScope.BOTH);
  const [selectedRoleKey, setSelectedRoleKey] = useState<UserRole>(UserRole.ADMIN);
  const { pending: savingUser, run: runSaveUser } = useSingleFlight();
  const [transferConfirmed, setTransferConfirmed] = useState(false);
  // One row mutation (B2B review, scope change, (de)activate) at a time; the key is the user id.
  const {
    pending: rowActionPending,
    pendingKey: busyUserId,
    run: runRowAction,
  } = useSingleFlight();

  const fetchUsers = useCallback(async () => {
    const cached = getCachedQuery<UserRead[]>(cacheKey);
    if (cached !== null) {
      setUsers(cached);
      setLoading(false);
    }
    try {
      const data = await UsersService.listUsersInTenant();
      setCachedQuery(cacheKey, data);
      setUsers(data);
    } catch (error: unknown) {
      if (cached === null) {
        toast.error(extractApiErrorMessage(error, "Failed to load users"));
      }
    } finally {
      setLoading(false);
    }
  }, [cacheKey]);

  useEffect(() => {
    if (canManageTeam) {
      fetchUsers();
    }
  }, [canManageTeam, fetchUsers]);

  const pendingB2bRequests = useMemo(() => {
    return users.filter((u) => u.b2b_request_status === "PENDING");
  }, [users]);

  const openEditModal = (targetUser: UserRead) => {
    setEditingUser(targetUser);
    setFullNameInput(targetUser.full_name || "");
    setTransferConfirmed(false);
    setEmailInput(targetUser.email);
    setPhoneInput(targetUser.phone || "");
    setCompanyNameInput(targetUser.company_name || "");
    setGstinInput(targetUser.gstin || "");
    setPanInput(targetUser.pan || "");
    setIsActiveInput(targetUser.is_active);
    const resolvedRole = _resolveUserRole(targetUser);
    setSelectedRoleKey(resolvedRole);
    setScopeInput(
      targetUser.service_scope ||
        (resolvedRole === UserRole.CUSTOMER ? ServiceScope.B2C : ServiceScope.BOTH)
    );
    setModalOpen(true);
  };

  const handleGstinInputChange = (rawVal: string) => {
    const cleaned = rawVal.toUpperCase().replace(/\s+/g, "").slice(0, 15);
    setGstinInput(cleaned);
    if (cleaned.length >= 12 && !panInput.trim()) {
      setPanInput(cleaned.slice(2, 12));
    }
  };

  const handlePanInputChange = (rawVal: string) => {
    const cleaned = rawVal.toUpperCase().replace(/\s+/g, "").slice(0, 10);
    setPanInput(cleaned);
  };

  const handleReviewB2bRequest = (targetUser: UserRead, approve: boolean) =>
    runRowAction(async () => {
      try {
        await UsersService.reviewUserB2BAccessRequest(targetUser.id, {
          approve,
          service_scope: approve ? ServiceScope.BOTH : ServiceScope.B2C,
        });
        toast.success(
          approve
            ? `Approved B2B Cargo access for ${targetUser.email}`
            : `Declined B2B Cargo request for ${targetUser.email}`
        );
        await fetchUsers();
      } catch (error: unknown) {
        toast.error(extractApiErrorMessage(error, "Could not review B2B request"));
      }
    }, targetUser.id);

  const handleSaveUserModal = async () => {
    if (!editingUser) return;
    const transfersOwnership = isOwnershipTransfer(editingUser, selectedRoleKey);
    if (transfersOwnership && !transferConfirmed) {
      toast.error("Tick the box to confirm you are handing over the Owner role.");
      return;
    }

    const isCustomerRole = selectedRoleKey === UserRole.CUSTOMER;
    await runSaveUser(async () => {
      try {
        const updatePayload: UserUpdate = {
          phone: phoneInput.trim() || null,
          is_active: isActiveInput,
          account_type: isCustomerRole ? "CUSTOMER" : "TENANT_STAFF",
          role: selectedRoleKey,
          service_scope: isCustomerRole ? scopeInput : ServiceScope.BOTH,
          company_name: companyNameInput.trim() || null,
          gstin: gstinInput.trim() || null,
          pan: panInput.trim() || null,
        };
        if (fullNameInput.trim()) {
          updatePayload.full_name = fullNameInput.trim();
        }
        await UsersService.updateUserRole(editingUser.id, updatePayload);
        if (transfersOwnership) {
          toast.success(
            `${editingUser.email} is now the Owner. You are now an Admin; reloading your access.`
          );
          window.location.reload();
          return;
        }
        toast.success(
          `Updated ${editingUser.email} (${ROLE_LABEL_BY_KEY[selectedRoleKey]})`
        );
        setModalOpen(false);
        fetchUsers();
      } catch (error: unknown) {
        toast.error(extractApiErrorMessage(error, "Could not save user changes"));
      }
    });
  };

  const changeScopeQuick = (userId: string, newScope: ServiceScope) =>
    runRowAction(async () => {
      try {
        await UsersService.updateUserRole(userId, {
          service_scope: newScope,
        });
        toast.success(`Service scope updated to ${newScope}`);
        fetchUsers();
      } catch (error: unknown) {
        toast.error(extractApiErrorMessage(error, "Scope update failed"));
      }
    }, userId);

  const toggleActiveQuick = (userId: string, currentActive: boolean) =>
    runRowAction(async () => {
      try {
        await UsersService.updateUserRole(userId, {
          is_active: !currentActive,
        });
        toast.success(currentActive ? "User deactivated" : "User activated");
        fetchUsers();
      } catch (error: unknown) {
        toast.error(extractApiErrorMessage(error, "Status update failed"));
      }
    }, userId);

  const filteredUsers = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    return sortUsersForTable(users).filter((u) => {
      const displayName = (u.full_name || "").toLowerCase();
      const email = u.email.toLowerCase();
      const company = (u.company_name || "").toLowerCase();
      const gstin = (u.gstin || "").toLowerCase();
      const pan = (u.pan || "").toLowerCase();
      const matchesSearch =
        !query ||
        email.includes(query) ||
        displayName.includes(query) ||
        company.includes(query) ||
        gstin.includes(query) ||
        pan.includes(query);

      const resolvedRole = _resolveUserRole(u);
      const matchesRole = roleFilter === "ALL" || resolvedRole === roleFilter;

      const matchesStatus =
        statusFilter === "ALL" ||
        (statusFilter === "ACTIVE" && u.is_active) ||
        (statusFilter === "INACTIVE" && !u.is_active);

      return matchesSearch && matchesRole && matchesStatus;
    });
  }, [users, searchQuery, roleFilter, statusFilter]);

  const activeRoleDefinition = useMemo(() => {
    return (
      USER_ROLES.find((r) => r.key === selectedRoleKey) || USER_ROLES[1]
    );
  }, [selectedRoleKey]);

  const actor = currentUser ? { id: currentUser.id, role: currentUser.role } : null;
  const editPolicy = editingUser ? getUserEditPolicy(actor, editingUser) : null;
  const pendingTransfer =
    editingUser !== null && isOwnershipTransfer(editingUser, selectedRoleKey);

  if (!canManageTeam) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-center space-y-4">
        <ShieldAlert className="h-16 w-16 text-rose-500" />
        <h2 className="text-2xl font-bold text-slate-900">Access Denied</h2>
        <p className="text-slate-500">
          Only the workspace Owner or an Admin can manage users.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      {/* Header matching Delhivery One Settings -> Users (snipit_05d5lvgvueb2g.png) */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-slate-900">Users</h1>
            <button
              type="button"
              onClick={() => setRolesHelpOpen(true)}
              data-testid="team.roles-help"
              className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 border border-slate-200 hover:bg-slate-200 transition-colors"
            >
              <HelpCircle className="h-3.5 w-3.5 text-primary" />
              Roles &amp; permissions
            </button>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            People create their own account on the login page (password or email OTP)
            and start as a Customer. Use <strong className="font-semibold text-slate-700">Edit</strong> to
            give them a team role, B2C / B2B access, or deactivate them.
          </p>
        </div>
      </div>

      {/* Pending B2B Cargo Access Requests Banner (Admin Approval Queue) */}
      {pendingB2bRequests.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100 text-amber-800">
                <Clock className="h-4 w-4" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-slate-900">
                  Pending B2B Heavy Cargo Access Requests ({pendingB2bRequests.length})
                </h2>
                <p className="text-xs text-slate-600">
                  Review merchant B2B onboarding requests and optional GSTIN / PAN details.
                </p>
              </div>
            </div>
          </div>

          <div className="divide-y divide-amber-200/60 rounded-lg border border-amber-200/80 bg-white">
            {pendingB2bRequests.map((reqUser) => {
              const displayName =
                reqUser.full_name || reqUser.email.split("@")[0].toUpperCase();
              const isBusy = busyUserId === reqUser.id;
              return (
                <div
                  key={reqUser.id}
                  className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-3.5"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-bold text-slate-900">
                        {displayName}
                      </span>
                      <span className="text-xs text-slate-500">{reqUser.email}</span>
                      <Badge
                        variant="outline"
                        className="bg-amber-50 text-amber-800 border-amber-300 text-[10px] font-bold"
                      >
                        B2B REQUEST PENDING
                      </Badge>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      {reqUser.company_name && (
                        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 font-medium text-slate-700">
                          <Building2 className="h-3 w-3 text-slate-500" />
                          {reqUser.company_name}
                        </span>
                      )}
                      {reqUser.gstin && (
                        <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] font-semibold text-slate-700">
                          GSTIN: {reqUser.gstin}
                        </span>
                      )}
                      {reqUser.pan && (
                        <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] font-semibold text-slate-700">
                          PAN: {reqUser.pan}
                        </span>
                      )}
                      {!reqUser.company_name && !reqUser.gstin && !reqUser.pan && (
                        <span className="text-slate-400">
                          No GSTIN / PAN provided (optional)
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      type="button"
                      size="sm"
                      disabled={rowActionPending}
                      onClick={() => handleReviewB2bRequest(reqUser, true)}
                      className="h-8 px-3 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5"
                    >
                      {isBusy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-3.5 w-3.5" />
                      )}
                      Approve B2B
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={rowActionPending}
                      onClick={() => handleReviewB2bRequest(reqUser, false)}
                      className="h-8 px-3 text-xs font-semibold border-rose-200 text-rose-700 hover:bg-rose-50 gap-1"
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      Reject
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Filter Bar */}
      <div className="flex min-w-0 flex-col sm:flex-row gap-3">
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <Input
            placeholder="Search User by Email, Name, Company, GSTIN, or PAN"
            className="min-w-0 w-full pl-9 bg-white border-slate-200 shadow-sm rounded-lg"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="flex min-w-0 flex-wrap gap-3">
          <select
            aria-label="Select Status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-9 min-w-0 max-w-full rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            <option value="ALL">Select Status: All</option>
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Inactive</option>
          </select>

          <select
            aria-label="Select Role"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="h-9 min-w-0 max-w-full rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            <option value="ALL">Select Role: All</option>
            {USER_ROLES.map((roleDef) => (
              <option key={roleDef.key} value={roleDef.key}>
                {roleDef.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Users Table matching Delhivery One */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <th className="py-3.5 px-4">NAME</th>
                <th className="py-3.5 px-4">CREATED ON</th>
                <th className="py-3.5 px-4">ROLE TYPE</th>
                <th className="py-3.5 px-4">STATUS</th>
                <th className="py-3.5 px-4 text-right">ACTION</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm">
              {loading && users.length === 0 ? (
                <tr data-testid="team-users-loading-skeleton">
                  <td colSpan={5} className="py-10 px-4">
                    <div className="space-y-2.5">
                      {[0, 1, 2, 3].map((idx) => (
                        <div
                          key={idx}
                          className="h-10 w-full rounded-lg bg-slate-100 animate-pulse"
                        />
                      ))}
                    </div>
                  </td>
                </tr>
              ) : filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-sm text-slate-500">
                    No matching users found.
                  </td>
                </tr>
              ) : (
                filteredUsers.map((u) => {
                  const userRoleKey = _resolveUserRole(u);
                  const roleLabel = ROLE_LABEL_BY_KEY[userRoleKey];
                  const displayName =
                    u.full_name || u.email.split("@")[0].toUpperCase();
                  const rowPolicy = getUserEditPolicy(actor, u);
                  const canModifyStatus = !rowPolicy.statusLocked;

                  return (
                    <tr key={u.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-3">
                          <div className="h-9 w-9 rounded-full bg-slate-800 text-white flex items-center justify-center text-xs font-bold shrink-0">
                            {getInitials(u.full_name, u.email)}
                          </div>
                          <div>
                            <div className="font-bold text-slate-900">
                              {displayName}
                            </div>
                            <div className="text-xs text-slate-500">{u.email}</div>
                            {u.phone && (
                              <div className="text-[11px] text-slate-400">
                                {formatUserPhone(u.phone)}
                              </div>
                            )}
                            {(u.company_name || u.gstin || u.pan) && (
                              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                                {u.company_name && (
                                  <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-700">
                                    <Building2 className="h-2.5 w-2.5 text-slate-500" />
                                    {u.company_name}
                                  </span>
                                )}
                                {u.gstin && (
                                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-600">
                                    GSTIN: {u.gstin}
                                  </span>
                                )}
                                {u.pan && (
                                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-600">
                                    PAN: {u.pan}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>

                      <td className="py-3.5 px-4 text-slate-700 font-medium whitespace-nowrap">
                        {_formatCreatedDate(u.created_at)}
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="inline-flex items-center gap-1.5 text-slate-800 font-medium">
                            <UserCheck className="h-4 w-4 text-slate-500" />
                            {roleLabel}
                          </span>
                          {_renderScopePill(u.service_scope)}
                          {u.b2b_request_status === "PENDING" && (
                            <Badge
                              variant="outline"
                              className="bg-amber-50 text-amber-800 border-amber-300 text-[10px] font-bold"
                            >
                              B2B REQUEST PENDING
                            </Badge>
                          )}
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        {u.is_active ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                            Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 border border-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-600">
                            <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                            Inactive
                          </span>
                        )}
                      </td>

                      <td className="py-3.5 px-4 text-right">
                        <div className="inline-flex items-center gap-1">
                          {u.b2b_request_status === "PENDING" && (
                            <Button
                              type="button"
                              size="sm"
                              disabled={rowActionPending}
                              onClick={() => handleReviewB2bRequest(u, true)}
                              className="h-8 px-2.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white gap-1"
                            >
                              {busyUserId === u.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <CheckCircle2 className="h-3.5 w-3.5" />
                              )}
                              Approve B2B
                            </Button>
                          )}

                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => openEditModal(u)}
                            className="h-8 px-2.5 text-xs font-semibold text-primary hover:text-primary hover:bg-primary/10 gap-1.5"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                            Edit
                          </Button>

                          {(rowPolicy.canChangeScope || canModifyStatus) ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                className="h-8 w-8 p-0"
                                aria-label={`More actions for ${u.email}`}
                                disabled={rowActionPending}
                              >
                                {busyUserId === u.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
                                ) : (
                                  <MoreHorizontal className="h-4 w-4 text-slate-500" />
                                )}
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {rowPolicy.canChangeScope && (
                                <>
                              <DropdownMenuLabel>Service Scope</DropdownMenuLabel>
                              <DropdownMenuItem
                                onClick={() => changeScopeQuick(u.id, ServiceScope.B2C)}
                              >
                                <Package className="mr-2 h-4 w-4 text-sky-600" />
                                B2C Express
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() => changeScopeQuick(u.id, ServiceScope.B2B)}
                              >
                                <Truck className="mr-2 h-4 w-4 text-amber-600" />
                                B2B Heavy Cargo
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() => changeScopeQuick(u.id, ServiceScope.BOTH)}
                              >
                                <Layers className="mr-2 h-4 w-4 text-emerald-600" />
                                Unified (B2C &amp; B2B)
                              </DropdownMenuItem>
                                </>
                              )}
                              {canModifyStatus && (
                                <>
                                  {rowPolicy.canChangeScope && <DropdownMenuSeparator />}
                                  <DropdownMenuItem
                                    onClick={() => toggleActiveQuick(u.id, u.is_active)}
                                    className={
                                      u.is_active ? "text-rose-600" : "text-emerald-600"
                                    }
                                  >
                                    {u.is_active ? "Deactivate User" : "Activate User"}
                                  </DropdownMenuItem>
                                </>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                          ) : (
                            <span className="inline-block h-8 w-8" aria-hidden />
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Footer: every matching user is listed (no pagination) */}
        <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50/60 px-4 py-2.5 text-xs text-slate-500">
          <span>
            Showing{" "}
            <strong className="text-slate-700">
              {filteredUsers.length > 0 ? 1 : 0} - {filteredUsers.length}
            </strong>{" "}
            of <strong className="text-slate-700">{filteredUsers.length}</strong>
          </span>
        </div>
      </div>

      {/* Add & Invite Users / Edit User Modal matching snipit_12p2vmachtcm8.png & snipit_52b9kms8ft1j0.png */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="sm:max-w-2xl p-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-3">
            <DialogTitle className="text-xl font-bold text-slate-900">
              Edit User
            </DialogTitle>
            <DialogDescription className="sr-only">
              Configure user profile, account status, service permission scope, optional GSTIN/PAN, and role capabilities.
            </DialogDescription>
          </DialogHeader>

          <div className="px-6 pb-5 max-h-[75vh] overflow-y-auto overflow-x-hidden space-y-5 min-w-0">
            {/* Row 1: Full Name + Status Radio */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-center min-w-0">
              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="user-full-name" className="text-xs font-semibold text-slate-700">
                  Full Name
                </Label>
                <Input
                  id="user-full-name"
                  value={fullNameInput}
                  onChange={(e) => setFullNameInput(e.target.value)}
                  placeholder="Enter Full Name"
                  className="min-w-0 w-full text-sm"
                />
              </div>

              <div className="min-w-0 space-y-2">
                <Label className="text-xs font-semibold text-slate-700 block">
                  Status
                </Label>
                <div className="flex items-center gap-5 pt-1">
                  <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-800 cursor-pointer">
                    <input
                      type="radio"
                      name="user-status"
                      checked={isActiveInput}
                      onChange={() => setIsActiveInput(true)}
                      disabled={editPolicy?.statusLocked ?? true}
                      className="h-4 w-4 accent-primary"
                    />
                    <span>Active</span>
                  </label>

                  <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-800 cursor-pointer">
                    <input
                      type="radio"
                      name="user-status"
                      checked={!isActiveInput}
                      onChange={() => setIsActiveInput(false)}
                      disabled={editPolicy?.statusLocked ?? true}
                      className="h-4 w-4 accent-primary"
                    />
                    <span>Inactive</span>
                  </label>
                </div>
              </div>
            </div>

            {/* Row 2: Mobile Number (+91 prefix) + Email ID */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 min-w-0">
              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="user-phone" className="text-xs font-semibold text-slate-700">
                  Mobile Number
                </Label>
                <div className="flex min-w-0 items-center rounded-md border border-slate-200 bg-white overflow-hidden">
                  <span className="px-3 py-2 text-xs font-semibold text-slate-500 bg-slate-50 border-r border-slate-200 shrink-0">
                    +91
                  </span>
                  <Input
                    id="user-phone"
                    value={phoneInput}
                    onChange={(e) => setPhoneInput(e.target.value)}
                    placeholder="Enter Mobile Number"
                    className="min-w-0 flex-1 border-0 shadow-none focus-visible:ring-0 text-sm"
                  />
                </div>
              </div>

              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="user-email" className="text-xs font-semibold text-slate-700">
                  Email ID
                </Label>
                <Input
                  id="user-email"
                  type="email"
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  readOnly
                  placeholder="Enter Email ID"
                  className={
                    "min-w-0 w-full bg-slate-100 text-slate-500 cursor-not-allowed text-sm"
                  }
                />
              </div>
            </div>

            {/* Single Unified 2-Column Roles Selector & Capability Checklist */}
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-4 space-y-3">
              <div className="flex items-center gap-2">
                <div className="h-7 w-7 rounded-md bg-slate-100 flex items-center justify-center">
                  <FileSpreadsheet className="h-4 w-4 text-slate-700" />
                </div>
                <span className="text-sm font-bold text-slate-900">Roles</span>
              </div>

              <p className="text-xs text-slate-500">Choose a Role</p>
              {editPolicy?.lockReason && (
                <p
                  className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                  data-testid="team.edit.lock-reason"
                >
                  {editPolicy.lockReason}
                </p>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 pt-1">
                {/* Left Column: Single Unified Selectable Role List */}
                <div className="sm:col-span-5 flex flex-col gap-1 border-r border-slate-100 pr-2">
                  {USER_ROLES.map((roleDef) => {
                    const isSelected = selectedRoleKey === roleDef.key;
                    const isDisabled =
                      !isSelected && (editPolicy?.disabledRoles.has(roleDef.key) ?? true);
                    return (
                      <button
                        key={roleDef.key}
                        type="button"
                        disabled={isDisabled}
                        onClick={() => {
                          setSelectedRoleKey(roleDef.key);
                          setTransferConfirmed(false);
                          if (roleDef.key === UserRole.CUSTOMER) {
                            setScopeInput(ServiceScope.B2C);
                          } else {
                            setScopeInput(ServiceScope.BOTH);
                          }
                        }}
                        className={
                          isSelected
                            ? "text-left px-3 py-2 rounded-md bg-primary/10 border-l-4 border-primary text-xs font-bold text-primary transition-all"
                            : "text-left px-3 py-2 rounded-md hover:bg-slate-50 text-xs font-medium text-slate-700 transition-all disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                        }
                      >
                        {roleDef.label}
                      </button>
                    );
                  })}
                </div>

                {/* Right Column: "{SelectedRole} Can do" Capability Checklist */}
                <div className="sm:col-span-7 pl-1 space-y-2.5">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                    <span className="text-xs font-bold text-slate-900">
                      {activeRoleDefinition.label} Can do
                    </span>
                  </div>

                  <ul className="space-y-1.5 text-xs text-slate-700 list-disc pl-6">
                    {activeRoleDefinition.capabilities.map((capabilityText) => (
                      <li key={capabilityText} className="leading-relaxed">
                        {capabilityText}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            {selectedRoleKey === UserRole.CUSTOMER ? (
              <>
                {/* Account Permission (B2C / B2B Service Scope provided to Customer) */}
                <div className="space-y-1.5">
                  <Label className="text-xs font-semibold text-slate-700">
                    Services Provided to Customer (B2C vs B2B)
                  </Label>
                  <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3 flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-slate-700 mr-2">
                      Enabled Flows:
                    </span>
                    {SERVICE_SCOPE_CHOICES.map((choice) => {
                      const isSelected = scopeInput === choice.value;
                      return (
                        <button
                          key={choice.value}
                          type="button"
                          onClick={() => setScopeInput(choice.value)}
                          className={
                            isSelected
                              ? "rounded-full bg-slate-900 text-white px-3 py-1 text-xs font-semibold shadow-sm transition-colors"
                              : "rounded-full bg-slate-200/80 text-slate-700 hover:bg-slate-300 px-3 py-1 text-xs font-medium transition-colors"
                          }
                        >
                          {choice.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Optional B2B Business Details: Company Name, GSTIN, PAN */}
                <div className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-50/40 p-3.5 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Label className="text-xs font-semibold text-slate-700">
                      B2B Business &amp; Tax Details (Optional)
                    </Label>
                    <span className="text-[11px] text-slate-500">
                      Optional for B2B Cargo / GST Invoicing
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 min-w-0">
                    <div className="min-w-0 space-y-1">
                      <Label
                        htmlFor="user-company-name"
                        className="text-[11px] font-medium text-slate-600"
                      >
                        Company Name (Optional)
                      </Label>
                      <Input
                        id="user-company-name"
                        value={companyNameInput}
                        onChange={(e) => setCompanyNameInput(e.target.value)}
                        placeholder="e.g. Acme Logistics"
                        className="min-w-0 w-full h-8 text-xs bg-white"
                      />
                    </div>
                    <div className="min-w-0 space-y-1">
                      <Label
                        htmlFor="user-gstin"
                        className="text-[11px] font-medium text-slate-600"
                      >
                        GSTIN (Optional)
                      </Label>
                      <Input
                        id="user-gstin"
                        value={gstinInput}
                        onChange={(e) => handleGstinInputChange(e.target.value)}
                        placeholder="29ABCDE1234F1Z5"
                        maxLength={15}
                        className="min-w-0 w-full h-8 font-mono text-xs uppercase bg-white"
                      />
                    </div>
                    <div className="min-w-0 space-y-1">
                      <Label
                        htmlFor="user-pan"
                        className="text-[11px] font-medium text-slate-600"
                      >
                        PAN (Optional)
                      </Label>
                      <Input
                        id="user-pan"
                        value={panInput}
                        onChange={(e) => handlePanInputChange(e.target.value)}
                        placeholder="ABCDE1234F"
                        maxLength={10}
                        className="min-w-0 w-full h-8 font-mono text-xs uppercase bg-white"
                      />
                    </div>
                  </div>
                </div>
              </>
            ) : pendingTransfer ? (
              <div
                className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900 space-y-2"
                data-testid="team.edit.transfer-warning"
              >
                <p>
                  <strong className="font-semibold">Hand over the Owner role.</strong>{" "}
                  {editingUser?.email} becomes the Owner and you become an Admin. Only the new
                  Owner can change Admins or give the Owner role back.
                </p>
                <label className="flex items-center gap-2 font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    checked={transferConfirmed}
                    onChange={(e) => setTransferConfirmed(e.target.checked)}
                    data-testid="team.edit.transfer-confirm"
                    className="h-4 w-4 accent-primary"
                  />
                  I understand, transfer ownership
                </label>
              </div>
            ) : (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                <strong className="font-semibold text-slate-900">
                  Team role ({activeRoleDefinition.label}):
                </strong>{" "}
                Saving gives this signed-up user the{" "}
                <strong className="font-semibold text-slate-900">
                  {activeRoleDefinition.label}
                </strong>{" "}
                permissions listed above, with access to both B2C and B2B. Their next page
                load picks up the new role.
              </div>
            )}
          </div>

          {/* Modal Footer */}
          <div className="flex items-center justify-end gap-2.5 border-t border-slate-200 bg-white px-6 py-3.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setModalOpen(false)}
              className="h-9 px-4 text-xs font-semibold"
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={savingUser || (pendingTransfer && !transferConfirmed)}
              onClick={handleSaveUserModal}
              className="h-9 px-5 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white"
            >
              {savingUser ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Saving
                </>
              ) : pendingTransfer ? (
                "Transfer ownership"
              ) : (
                "Save Changes"
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Roles & permissions (Delhivery One `users`: "What permissions does each user role have?") */}
      <Dialog open={rolesHelpOpen} onOpenChange={setRolesHelpOpen}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Roles &amp; permissions</DialogTitle>
            <DialogDescription>
              New people sign up on the login page and start as a Customer. Open{" "}
              <strong>Edit</strong> to give them a team role. Only the Owner can add or change
              Admins or hand over the Owner role; users are deactivated, never deleted.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto grid grid-cols-1 gap-3 sm:grid-cols-2">
            {USER_ROLES.map((roleDef) => (
              <div key={roleDef.key} className="rounded-lg border border-slate-200 p-3">
                <p className="text-sm font-bold text-slate-900">{roleDef.label}</p>
                <ul className="mt-1.5 list-disc space-y-1 pl-5 text-xs text-slate-700">
                  {roleDef.capabilities.map((capabilityText) => (
                    <li key={capabilityText}>{capabilityText}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
