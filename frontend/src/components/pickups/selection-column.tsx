// frontend/src/components/pickups/selection-column.tsx
"use client";

/**
 * Reusable TanStack checkbox column for row multi-selection.
 *
 * `DataTable` is a presentational wrapper without built-in selection, so the
 * selected ids live in the page state and are passed in here (controlled
 * component). The header checkbox toggles every selectable row on the
 * current page. Checkbox clicks never bubble to `onRowClick`.
 */
import type { ColumnDef } from "@tanstack/react-table";

const CHECKBOX_CLASS =
  "h-4 w-4 rounded border-input bg-background accent-primary cursor-pointer disabled:cursor-not-allowed disabled:opacity-40";

/** Controlled selection state + callbacks for `buildSelectionColumn`. */
export interface RowSelectionOptions<TRow> {
  /** Ids currently selected (page state). */
  selectedIds: ReadonlySet<string>;
  /** Toggles a single row. */
  onToggle: (id: string) => void;
  /** Selects (`checked = true`) or clears the given ids. */
  onToggleMany: (ids: string[], checked: boolean) => void;
  /** Whether a row may be selected; non-selectable rows render a disabled box. */
  isSelectable: (row: TRow) => boolean;
  /** Accessible label suffix, e.g. "shipment". */
  rowNoun: string;
}

/**
 * Builds a leading checkbox column.
 *
 * @param options - Controlled selection state and callbacks.
 * @returns A TanStack column definition with id `select`.
 */
export function buildSelectionColumn<TRow extends { id: string }>(
  options: RowSelectionOptions<TRow>
): ColumnDef<TRow> {
  const { selectedIds, onToggle, onToggleMany, isSelectable, rowNoun } = options;
  return {
    id: "select",
    enableSorting: false,
    header: ({ table }) => {
      const selectableIds = table
        .getRowModel()
        .rows.map((row) => row.original)
        .filter(isSelectable)
        .map((row) => row.id);
      const allSelected =
        selectableIds.length > 0 && selectableIds.every((id) => selectedIds.has(id));
      return (
        <input
          type="checkbox"
          aria-label={`Select all ${rowNoun}s on this page`}
          className={CHECKBOX_CLASS}
          checked={allSelected}
          disabled={selectableIds.length === 0}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => onToggleMany(selectableIds, event.target.checked)}
        />
      );
    },
    cell: ({ row }) => {
      const selectable = isSelectable(row.original);
      return (
        <input
          type="checkbox"
          aria-label={`Select ${rowNoun}`}
          className={CHECKBOX_CLASS}
          checked={selectable && selectedIds.has(row.original.id)}
          disabled={!selectable}
          onClick={(event) => event.stopPropagation()}
          onChange={() => onToggle(row.original.id)}
        />
      );
    },
  };
}
