// frontend/src/app/[tenant_slug]/(app)/team/page.tsx
"use client";

import { UserRead, UserRole, UsersService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ColumnDef } from "@tanstack/react-table";
import {
  Filter,
  Loader2,
  MoreHorizontal,
  Search,
  Shield,
  ShieldAlert,
  UserIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

export default function TeamManagementPage() {
  const { isAdmin, user: currentUser } = useUser();
  const [users, setUsers] = useState<UserRead[]>([]);
  const [loading, setLoading] = useState(true);

  // 🔥 NEW: Filter States
  const [searchQuery, setSearchQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");

  const fetchUsers = async () => {
    try {
      const data = await UsersService.listUsersInTenant();
      setUsers(data);
    } catch (error) {
      toast.error("Failed to load team");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) fetchUsers();
  }, [isAdmin]);

  const changeRole = async (userId: string, newRole: UserRole) => {
    try {
      await UsersService.updateUserRole(userId, { role: newRole } as any);
      toast.success("User role updated");
      fetchUsers();
    } catch (error: any) {
      toast.error(error.body?.detail || "Update failed");
    }
  };

  const toggleActive = async (userId: string, currentActive: boolean) => {
    try {
      await UsersService.updateUserRole(userId, {
        is_active: !currentActive,
      } as any);
      toast.success(currentActive ? "User deactivated" : "User activated");
      fetchUsers();
    } catch (error: any) {
      toast.error(error.body?.detail || "Update failed");
    }
  };

  // 🔥 NEW: Client-side filtering engine
  const filteredUsers = useMemo(() => {
    return users.filter((u) => {
      // 1. Text Search (Email)
      const matchesSearch = u.email
        .toLowerCase()
        .includes(searchQuery.toLowerCase().trim());

      // 2. Role Filter
      const matchesRole = roleFilter === "ALL" || u.role === roleFilter;

      // 3. Status Filter
      const matchesStatus =
        statusFilter === "ALL" ||
        (statusFilter === "ACTIVE" && u.is_active) ||
        (statusFilter === "SUSPENDED" && !u.is_active);

      return matchesSearch && matchesRole && matchesStatus;
    });
  }, [users, searchQuery, roleFilter, statusFilter]);

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-center space-y-4">
        <ShieldAlert className="h-16 w-16 text-red-500" />
        <h2 className="text-2xl font-bold text-slate-900">Access Denied</h2>
        <p className="text-slate-500">Only Admins can manage team access.</p>
      </div>
    );
  }

  const columns: ColumnDef<UserRead>[] = [
    {
      accessorKey: "email",
      header: "Email Address",
      cell: ({ row }) => (
        <span className="font-bold">{row.original.email}</span>
      ),
    },
    {
      accessorKey: "role",
      header: "Access Level",
      cell: ({ row }) => (
        <Badge
          variant={
            row.original.role === UserRole.OWNER
              ? "destructive"
              : row.original.role === UserRole.ADMIN
              ? "default"
              : "outline"
          }
        >
          {row.original.role.toUpperCase()}
        </Badge>
      ),
    },
    {
      accessorKey: "is_active",
      header: "Status",
      cell: ({ row }) => (
        <span
          className={
            row.original.is_active
              ? "text-green-600 font-semibold"
              : "text-red-500 font-semibold"
          }
        >
          {row.original.is_active ? "Active" : "Suspended"}
        </span>
      ),
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const u = row.original;
        if (u.role === UserRole.OWNER)
          return <span className="text-xs text-slate-400">System Owner</span>;
        if (u.id === currentUser?.id)
          return <span className="text-xs text-slate-400">You</span>;

        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Permissions</DropdownMenuLabel>
              <DropdownMenuItem
                onClick={() => changeRole(u.id, UserRole.ADMIN)}
              >
                <Shield className="mr-2 h-4 w-4 text-blue-500" /> Make Admin
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => changeRole(u.id, UserRole.CUSTOMER)}
              >
                <UserIcon className="mr-2 h-4 w-4 text-slate-500" /> Make
                Customer
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => toggleActive(u.id, u.is_active)}
                className={u.is_active ? "text-red-600" : "text-green-600"}
              >
                {u.is_active ? "Suspend User" : "Reactivate User"}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12">
      {/* Header */}
      <div className="border-b border-slate-200 pb-4">
        <h1 className="text-3xl font-bold text-slate-900">Team & Access</h1>
        <p className="text-slate-500 mt-1">
          Manage permissions for staff and customers in your workspace.
        </p>
      </div>

      {/* 🔥 NEW: Toolbar / Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search Bar */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <Input
            placeholder="Search by email..."
            className="pl-9 bg-white border-slate-200 shadow-sm rounded-lg"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {/* Dropdown Filters */}
        <div className="flex gap-3">
          <Select value={roleFilter} onValueChange={setRoleFilter}>
            <SelectTrigger className="w-[140px] bg-white border-slate-200 shadow-sm">
              <Filter className="w-3 h-3 mr-2 text-slate-400" />
              <SelectValue placeholder="Role" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Roles</SelectItem>
              <SelectItem value={UserRole.OWNER}>Owner</SelectItem>
              <SelectItem value={UserRole.ADMIN}>Admin</SelectItem>
              <SelectItem value={UserRole.CUSTOMER}>Customer</SelectItem>
            </SelectContent>
          </Select>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[140px] bg-white border-slate-200 shadow-sm">
              <Filter className="w-3 h-3 mr-2 text-slate-400" />
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Statuses</SelectItem>
              <SelectItem value="ACTIVE">Active</SelectItem>
              <SelectItem value="SUSPENDED">Suspended</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Data Table */}
      {loading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : (
        <DataTable columns={columns} data={filteredUsers} />
      )}
    </div>
  );
}
