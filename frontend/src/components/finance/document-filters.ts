// frontend/src/components/finance/document-filters.ts

/** Badge label for a GST document's type, from the backend `note_type`. */
export function documentTypeLabel(noteType: string | undefined | null): string {
  if (noteType === "CREDIT_NOTE") return "Credit note";
  if (noteType === "DEBIT_NOTE") return "Debit note";
  return "Invoice";
}

/** `yyyy-MM-dd` (the value format of `<input type="date">`) of an ISO timestamp, local time. */
export function toDateInputValue(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return [date.getFullYear(), pad(date.getMonth() + 1), pad(date.getDate())].join("-");
}

/**
 * True when the row's date falls inside the optional `from` / `to` date-input range
 * (both inclusive, `yyyy-MM-dd`). An empty bound is open; an unparseable date only
 * passes when no bound is set.
 */
export function isWithinDateRange(iso: string, from: string, to: string): boolean {
  const day = toDateInputValue(iso);
  if (!day) return !from && !to;
  if (from && day < from) return false;
  if (to && day > to) return false;
  return true;
}
