// frontend/src/app/[tenant_slug]/(app)/address-book/page.tsx
"use client";

import { AddressRead, AddressesService, AddressType } from "@/api_client";
import { AddAddressDialog } from "@/components/forms/add-address-dialog";
import { EditAddressDialog } from "@/components/forms/edit-address-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { columns } from "./columns";

export default function AddressBookPage() {
  const [data, setData] = useState<AddressRead[]>([]);
  const [loading, setLoading] = useState(true);

  // Dialog States
  const [editOpen, setEditOpen] = useState(false);
  const [selectedAddress, setSelectedAddress] = useState<AddressRead | null>(
    null
  );
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // 🔥 NEW: Filter States
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("ALL");

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
    } catch (e) {
      toast.error("Failed to delete address");
    }
  };

  // 🔥 NEW: Client-side filtering engine
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

      // 2. Exact Type Filter
      const typeMatch =
        typeFilter === "ALL" || addr.address_type === typeFilter;

      return searchMatch && typeMatch;
    });
  }, [data, searchQuery, typeFilter]);

  const actionColumns: ColumnDef<AddressRead>[] = [
    ...columns,
    {
      id: "actions",
      cell: ({ row }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="h-8 w-8 p-0">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              onClick={() => {
                setSelectedAddress(row.original);
                setEditOpen(true);
              }}
            >
              <Pencil className="mr-2 h-4 w-4" /> Edit
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => setDeleteConfirmId(row.original.id)}
              className="text-red-600 focus:text-red-700 focus:bg-red-50"
            >
              <Trash2 className="mr-2 h-4 w-4" /> Remove
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Address Book</h1>
          <p className="text-slate-500 mt-1">
            Manage your saved warehouses and customer addresses.
          </p>
        </div>
        <AddAddressDialog onSuccess={fetchAddresses} />
      </div>

      {/* 🔥 NEW: Toolbar / Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search Bar */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <Input
            placeholder="Search by name, phone, or city..."
            className="pl-9 bg-white border-slate-200 shadow-sm rounded-lg"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {/* Dropdown Filters */}
        <div className="flex gap-3">
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="w-[160px] bg-white border-slate-200 shadow-sm">
              <Filter className="w-3 h-3 mr-2 text-slate-400" />
              <SelectValue placeholder="Address Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Types</SelectItem>
              <SelectItem value={AddressType.CUSTOMER}>Customer</SelectItem>
              <SelectItem value={AddressType.WAREHOUSE}>Warehouse</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {loading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
        </div>
      ) : data.length === 0 ? (
        <div className="flex flex-col h-64 items-center justify-center border rounded-xl bg-white shadow-sm space-y-3">
          <MapPin className="h-10 w-10 text-slate-300" />
          <p className="text-slate-500 font-medium">No saved addresses yet.</p>
        </div>
      ) : (
        <DataTable columns={actionColumns} data={filteredData} />
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
            <Button variant="outline" onClick={() => setDeleteConfirmId(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={executeDelete}>
              Yes, Remove
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
