// frontend/src/components/ui/data-table.tsx
"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, SearchX } from "lucide-react";

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  onRowClick?: (row: TData) => void;
  // 🔥 NEW: Pagination Props
  pageCount?: number;
  pageIndex?: number;
  onNextPage?: () => void;
  onPreviousPage?: () => void;
  canNextPage?: boolean;
  canPreviousPage?: boolean;
}

export function DataTable<TData, TValue>({
  columns,
  data,
  onRowClick,
  pageCount = 1,
  pageIndex = 0,
  onNextPage,
  onPreviousPage,
  canNextPage = false,
  canPreviousPage = false,
}: DataTableProps<TData, TValue>) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true, // Tells TanStack we handle pagination on the server
    pageCount: pageCount,
  });

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm flex flex-col">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader className="bg-slate-50/80 border-b border-slate-200">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent">
                {headerGroup.headers.map((header) => {
                  return (
                    <TableHead
                      key={header.id}
                      className="font-bold text-slate-700 h-11 whitespace-nowrap"
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && "selected"}
                  onClick={() => onRowClick && onRowClick(row.original)}
                  className={
                    onRowClick
                      ? "cursor-pointer hover:bg-slate-50/80 transition-colors"
                      : ""
                  }
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="text-slate-600 py-3">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-64 text-center"
                >
                  <div className="flex flex-col items-center justify-center text-slate-500 space-y-3">
                    <div className="h-12 w-12 bg-slate-50 rounded-full flex items-center justify-center border border-slate-100">
                      <SearchX className="h-6 w-6 text-slate-400" />
                    </div>
                    <div>
                      <p className="font-semibold text-slate-900">
                        No records found
                      </p>
                      <p className="text-sm">
                        Try adjusting your filters or search query.
                      </p>
                    </div>
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* 🔥 NEW: Enterprise Pagination Footer */}
      {onNextPage && onPreviousPage && (
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-200 bg-slate-50/50 rounded-b-xl">
          <div className="text-sm font-medium text-slate-500">
            Page {pageIndex + 1} of {Math.max(1, pageCount)}
          </div>
          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onPreviousPage}
              disabled={!canPreviousPage}
              className="h-8 border-slate-200 text-slate-600 shadow-sm"
            >
              <ChevronLeft className="h-4 w-4 mr-1" /> Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onNextPage}
              disabled={!canNextPage}
              className="h-8 border-slate-200 text-slate-600 shadow-sm"
            >
              Next <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
