// src/app/[tenant_slug]/(app)/address-book/columns.tsx
"use client";

import { AddressRead, AddressCategory, AddressScope } from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { ColumnDef } from "@tanstack/react-table";
import { Phone, MapPin } from "lucide-react";

export const columns: ColumnDef<AddressRead>[] = [
  {
    accessorKey: "name",
    header: "Name / Company",
    cell: ({ row }) => {
      const name = row.getValue("name") as string;
      const company = row.original.company_name;
      const initial = name.charAt(0).toUpperCase();
      return (
        <div className="flex items-center gap-3 min-w-[180px]">
          <div className="h-9 w-9 rounded-full bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center font-extrabold text-sm shrink-0 shadow-xs">
            {initial}
          </div>
          <div className="flex flex-col">
            <span className="font-semibold text-slate-900 leading-tight">{name}</span>
            {company && <span className="text-[10px] font-bold text-indigo-600/80 uppercase tracking-wider mt-0.5">{company}</span>}
          </div>
        </div>
      );
    },
  },
  {
    accessorKey: "phone",
    header: "Phone",
    cell: ({ row }) => {
      const phone = row.getValue("phone") as string;
      const altPhone = row.original.alternate_phone;
      return (
        <div className="flex flex-col gap-1 min-w-[150px]">
          <div className="flex items-center gap-2 text-slate-700 font-semibold font-mono text-sm">
            <Phone className="h-3.5 w-3.5 text-slate-400 shrink-0" />
            {phone}
          </div>
          {altPhone && (
            <div className="flex items-center gap-1.5 text-slate-400 font-semibold font-mono text-[11px] mt-0.5">
              <span className="text-[9px] font-bold bg-slate-100 border border-slate-200/60 px-1 py-0.2 rounded uppercase tracking-wide text-slate-500">Alt</span>
              {altPhone}
            </div>
          )}
        </div>
      );
    },
  },
  {
    accessorKey: "address_line1",
    header: "Address",
    cell: ({ row }) => {
      const line1 = row.getValue("address_line1") as string;
      const city = row.original.city;
      const state = row.original.state;
      const pincode = row.original.pincode;
      return (
        <div className="flex items-start gap-2 min-w-[280px] max-w-[420px] whitespace-normal">
          <MapPin className="h-4 w-4 text-slate-400 shrink-0 mt-0.5" />
          <div className="flex flex-col">
            <span className="text-slate-700 text-sm leading-normal font-medium wrap-break-word">{line1}</span>
            <span className="text-slate-400 text-xs font-semibold mt-0.5 tracking-wide">{city}, {state} - {pincode}</span>
          </div>
        </div>
      );
    },
  },
  {
    accessorKey: "category",
    header: "Category",
    cell: ({ row }) => {
      const cat = row.getValue("category") as AddressCategory;
      
      const colors: Record<AddressCategory, string> = {
        [AddressCategory.HOME]: "bg-emerald-50 text-emerald-700 border-emerald-100",
        [AddressCategory.OFFICE]: "bg-blue-50 text-blue-700 border-blue-100",
        [AddressCategory.WAREHOUSE]: "bg-orange-50 text-orange-700 border-orange-100",
        [AddressCategory.STOREFRONT]: "bg-cyan-50 text-cyan-700 border-cyan-100",
        [AddressCategory.OTHER]: "bg-slate-50 text-slate-700 border-slate-100",
      };

      return (
        <div className="min-w-[110px] flex items-center">
          <Badge variant="outline" className={`font-bold tracking-wider text-[9px] uppercase px-2.5 py-1 border rounded-full shrink-0 ${colors[cat] || "bg-slate-50 text-slate-700"}`}>
            {cat}
          </Badge>
        </div>
      );
    },
  },
  {
    accessorKey: "scope",
    header: "Sharing Scope",
    cell: ({ row }) => {
      const scope = row.getValue("scope") as AddressScope;
      return (
        <div className="min-w-[110px] flex items-center">
          <Badge variant="outline" className={`font-bold tracking-wider text-[9px] uppercase px-2.5 py-1 border rounded-full shrink-0 ${
            scope === AddressScope.TENANT 
              ? "bg-purple-50 text-purple-700 border-purple-100" 
              : "bg-slate-50 text-slate-600 border-slate-200"
          }`}>
            {scope === AddressScope.TENANT ? "Team Shared" : "Private"}
          </Badge>
        </div>
      );
    },
  },
];
