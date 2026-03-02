// src/app/[tenant_slug]/(app)/address-book/columns.tsx
"use client";

import { AddressRead, AddressType } from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { ColumnDef } from "@tanstack/react-table";

export const columns: ColumnDef<AddressRead>[] = [
  {
    accessorKey: "name",
    header: "Name / Company",
    cell: ({ row }) => (
      <span className="font-semibold text-slate-900">
        {row.getValue("name")}
      </span>
    ),
  },
  {
    accessorKey: "phone",
    header: "Phone",
  },
  {
    accessorKey: "address_line1",
    header: "Address",
    cell: ({ row }) => {
      // We can combine multiple fields from the original data row!
      const city = row.original.city;
      const state = row.original.state;
      return (
        <span className="text-slate-500">
          {row.getValue("address_line1")}, {city}, {state}
        </span>
      );
    },
  },
  {
    accessorKey: "address_type",
    header: "Type",
    cell: ({ row }) => {
      const type = row.getValue("address_type") as AddressType;
      return (
        // 🔥 FIX: Changed 'secondary' to 'outline' so it's always readable
        <Badge variant={type === AddressType.WAREHOUSE ? "default" : "outline"}>
          {type.replace("_", " ")}
        </Badge>
      );
    },
  },
];
