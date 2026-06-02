// frontend/src/app/[tenant_slug]/(app)/address-book/page.tsx
"use client";

import { AddressRead, AddressesService, AddressCategory, AddressScope } from "@/api_client";
import { AddAddressDialog } from "@/components/forms/add-address-dialog";
import { EditAddressDialog } from "@/components/forms/edit-address-dialog";
import { Button } from "@/components/ui/button";
import { useUser } from "@/components/auth/auth-guard";
import { DataTable } from "@/components/ui/data-table";
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
  MapPin,
  MoreHorizontal,
  Pencil,
  Search,
  Trash2,
  BookOpen,
  Eye,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { columns } from "./columns";

export default function AddressBookPage() {
  const [data, setData] = useState<AddressRead[]>([]);
  const [loading, setLoading] = useState(true);
  const { user, isAdmin } = useUser();

  // Dialog States
  const [editOpen, setEditOpen] = useState(false);
  const [selectedAddress, setSelectedAddress] = useState<AddressRead | null>(
    null
  );
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Filter States
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [scopeFilter, setScopeFilter] = useState<string>("ALL");

  const fetchAddresses = async () => {
    setLoading(true);
    try {
      const response = await AddressesService.listSavedAddresses();
      setData(response);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAddresses();
  }, []);

  const executeDelete = async () => {
    if (!deleteConfirmId) return;
    try {
      await AddressesService.deleteSavedAddress(deleteConfirmId);
      toast.success("Address removed successfully");
      setDeleteConfirmId(null);
      fetchAddresses();
    } catch {
      toast.error("Failed to delete address");
    }
  };



  // Client-side filtering engine
  const filteredData = useMemo(() => {
    return data.filter((addr) => {
      // 1. Omni-Search Filter
      let searchMatch = true;
      if (searchQuery.trim() !== "") {
        const q = searchQuery.toLowerCase().trim();
        const searchableString = `
                    ${addr.name} 
                    ${addr.company_name || ""} 
                    ${addr.phone} 
                    ${addr.city} 
                    ${addr.state} 
                    ${addr.pincode}
                `.toLowerCase();
        searchMatch = searchableString.includes(q);
      }

      // 2. Exact Category Filter
      const categoryMatch =
        categoryFilter === "ALL" || addr.category === categoryFilter;

      // 3. Exact Scope Filter (Admins only)
      const scopeMatch =
        !isAdmin || scopeFilter === "ALL" || addr.scope === scopeFilter;

      return searchMatch && categoryMatch && scopeMatch;
    });
  }, [data, searchQuery, categoryFilter, scopeFilter, isAdmin]);

  const activeColumns: ColumnDef<AddressRead>[] = useMemo(() => {
    const baseCols: ColumnDef<AddressRead>[] = [
      ...columns,
      {
        id: "actions",
        cell: ({ row }) => {
          const isEditable = isAdmin || (row.original.scope === AddressScope.PRIVATE && row.original.user_id === user?.id);
          if (!isEditable) return null;

          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="h-8 w-8 p-0 cursor-pointer">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={() => {
                    setSelectedAddress(row.original);
                    setEditOpen(true);
                  }}
                  className="cursor-pointer"
                >
                  <Pencil className="mr-2 h-4 w-4" /> Edit
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => setDeleteConfirmId(row.original.id)}
                  className="text-red-600 focus:text-red-700 focus:bg-red-50 cursor-pointer"
                >
                  <Trash2 className="mr-2 h-4 w-4" /> Remove
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          );
        },
      },
    ];

    if (isAdmin) {
      return baseCols;
    }

    // Hide B2B Sharing Scope column for normal customers
    return baseCols.filter(
      (col) => !('accessorKey' in col && col.accessorKey === "scope")
    );
  }, [isAdmin, user]);

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-16 animate-in fade-in duration-300">
      {/* Title and Action bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 border-b border-slate-200/60 pb-6">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-slate-100 rounded-lg text-slate-900">
              <BookOpen className="h-6 w-6" />
            </div>
            <h1 className="text-3xl font-bold text-slate-900 tracking-tight">Address Book</h1>
          </div>
          <p className="text-slate-500 mt-2 text-sm leading-relaxed">
            {isAdmin 
              ? "Configure B2B shared warehouses, retail storefronts, and private team booking suggestions."
              : "Manage your private delivery addresses and origin contact locations."}
          </p>
        </div>
        <div className="shrink-0">
          <AddAddressDialog onSuccess={fetchAddresses} />
        </div>
      </div>



      {/* Filters Toolbar */}
      <div className="flex flex-col md:flex-row gap-4 bg-slate-50 p-4 rounded-xl border border-slate-200/60">
        {/* Search Bar */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <Input
            placeholder="Search by name, phone, company, or city..."
            className="pl-9 bg-white border-slate-200 shadow-xs rounded-lg text-sm focus:ring-slate-900 focus:border-slate-900"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {/* Dropdown Filters */}
        <div className="flex flex-wrap gap-3">
          {/* Category Select Filter */}
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="w-[160px] bg-white border-slate-200 shadow-xs rounded-lg text-sm font-medium text-slate-700">
              <Filter className="w-3.5 h-3.5 mr-2 text-slate-400" />
              <SelectValue placeholder="All Categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Categories</SelectItem>
              {Object.values(AddressCategory).map((cat) => (
                <SelectItem key={cat} value={cat}>
                  {cat}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Scope Select Filter (Admins only) */}
          {isAdmin && (
            <Select value={scopeFilter} onValueChange={setScopeFilter}>
              <SelectTrigger className="w-[160px] bg-white border-slate-200 shadow-xs rounded-lg text-sm font-medium text-slate-700 animate-in fade-in duration-150">
                <Eye className="w-3.5 h-3.5 mr-2 text-slate-400" />
                <SelectValue placeholder="All Scopes" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All Scopes</SelectItem>
                <SelectItem value={AddressScope.TENANT}>Team Shared</SelectItem>
                <SelectItem value={AddressScope.PRIVATE}>Private Only</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      {/* Table Block */}
      {loading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
        </div>
      ) : data.length === 0 ? (
        <div className="flex flex-col h-72 items-center justify-center border border-slate-200 rounded-xl bg-white shadow-xs space-y-4 text-center p-6">
          <div className="p-4 bg-slate-50 rounded-full text-slate-400">
            <MapPin className="h-8 w-8" />
          </div>
          <div>
            <h3 className="font-bold text-slate-900 text-base">No Saved Addresses Yet</h3>
            <p className="text-slate-500 text-xs mt-1 max-w-[250px] leading-normal">
              Your saved warehouses and booking customer suggestion entries will appear here.
            </p>
          </div>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          <DataTable columns={activeColumns} data={filteredData} />
        </div>
      )}

      <EditAddressDialog
        address={selectedAddress}
        open={editOpen}
        setOpen={setEditOpen}
        onSuccess={fetchAddresses}
      />

      <Dialog
        open={!!deleteConfirmId}
        onOpenChange={(open) => !open && setDeleteConfirmId(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle className="text-red-600 flex items-center gap-2">
              <Trash2 className="h-5 w-5" /> Remove Address
            </DialogTitle>
            <DialogDescription className="pt-2">
              Are you sure you want to remove this address from your address
              book? It will no longer appear in your dropdown suggestions.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-3 mt-4 border-t border-slate-100 pt-4">
            <Button variant="outline" className="cursor-pointer" onClick={() => setDeleteConfirmId(null)}>
              Cancel
            </Button>
            <Button variant="destructive" className="cursor-pointer" onClick={executeDelete}>
              Yes, Remove
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
