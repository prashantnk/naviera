// frontend/src/components/pricing-admin/prime-lane-row.tsx
"use client";

/**
 * One row of the Prime lanes table, with inline edit (Edit → type → Save) and an
 * "Active" switch. Saves via `PATCH /api/v1/pricing/prime-lanes/{id}`.
 */
import { Check, Loader2, Pencil, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { toast } from "sonner";

import { formatInr } from "@/components/shipments/shipment-money";
import { Button } from "@/components/ui/button";
import { InputAdornment } from "@/components/ui/form-extras";
import { Input } from "@/components/ui/input";
import { TableCell, TableRow } from "@/components/ui/table";
import { cn, extractApiErrorMessage } from "@/lib/utils";

import { patchPrimeLane, type PrimeLaneRead } from "./pricing-admin-api";
import {
  buildLanePatch,
  EDITABLE_LANE_COLUMNS,
  laneToDraft,
  type EditableLaneColumn,
  type LaneDraft,
  type LaneDraftErrors,
} from "./prime-lanes-logic";

const SAVE_ERROR_TEXT = "This lane was not saved.";

interface PrimeLaneRowProps {
  lane: PrimeLaneRead;
  tenantSlug: string | null | undefined;
  canEdit: boolean;
  /** Called with the saved lane after an inline edit. */
  onSaved: (lane: PrimeLaneRead) => void;
  /** Called after Active changes (other lanes on the route may change too). */
  onActiveChanged: () => void;
}

/**
 * Formats a stored lane number for read mode.
 *
 * @param lane - Lane from the API.
 * @param column - Column being shown.
 * @returns e.g. "₹500.00", "48 h" or "20%".
 */
function _formatCell(lane: PrimeLaneRead, column: EditableLaneColumn): string {
  const value = lane[column.field];
  if (column.prefix) return formatInr(value);
  if (column.suffix === "%") return `${value}%`;
  return column.suffix ? `${value} ${column.suffix}` : String(value);
}

/**
 * Renders one Prime lane.
 *
 * @param props - See `PrimeLaneRowProps`.
 */
export function PrimeLaneRow({ lane, tenantSlug, canEdit, onSaved, onActiveChanged }: PrimeLaneRowProps) {
  const [draft, setDraft] = useState<LaneDraft | null>(null);
  const [errors, setErrors] = useState<LaneDraftErrors>({});
  const [saving, setSaving] = useState(false);
  const testId = `prime-lanes.row.${lane.id}`;

  const cancel = () => {
    setDraft(null);
    setErrors({});
  };

  const save = async () => {
    if (!draft) return;
    const result = buildLanePatch(lane, draft);
    setErrors(result.errors);
    if (Object.keys(result.errors).length > 0) return;
    if (Object.keys(result.patch).length === 0) {
      cancel();
      return;
    }
    setSaving(true);
    try {
      const updated = await patchPrimeLane(lane.id, result.patch, tenantSlug);
      onSaved(updated);
      cancel();
      toast.success(`Lane ${lane.origin_zone} → ${lane.dest_zone} saved.`);
    } catch (err) {
      toast.error(extractApiErrorMessage(err, SAVE_ERROR_TEXT));
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (isActive: boolean) => {
    setSaving(true);
    try {
      await patchPrimeLane(lane.id, { is_active: isActive }, tenantSlug);
      toast.success(
        isActive
          ? `Lane switched on. Any other transporter on ${lane.origin_zone} → ${lane.dest_zone} was switched off.`
          : "Lane switched off. Customers can no longer book it.",
      );
      onActiveChanged();
    } catch (err) {
      toast.error(extractApiErrorMessage(err, SAVE_ERROR_TEXT));
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      save();
    } else if (event.key === "Escape") {
      cancel();
    }
  };

  return (
    <TableRow data-testid={testId} className={cn(!lane.is_active && "bg-slate-50 text-slate-500")}>
      <TableCell className="whitespace-nowrap font-semibold">
        {lane.origin_zone} <span className="text-slate-400">→</span> {lane.dest_zone}
      </TableCell>
      <TableCell className="whitespace-nowrap text-xs">{lane.transporter_name}</TableCell>
      {EDITABLE_LANE_COLUMNS.map((column) => (
        <TableCell key={column.field} className="min-w-24 align-top font-mono text-xs">
          {draft ? (
            <div className="min-w-0 space-y-1">
              <InputAdornment prefix={column.prefix} suffix={column.suffix}>
                <Input
                  value={draft[column.field]}
                  inputMode="decimal"
                  aria-label={column.label}
                  aria-invalid={Boolean(errors[column.field])}
                  disabled={saving}
                  onKeyDown={handleKeyDown}
                  onChange={(e) => setDraft(Object.assign({}, draft, { [column.field]: e.target.value }))}
                  data-testid={`${testId}.${column.field}`}
                  className="h-8 min-w-0 w-full bg-white font-mono text-xs"
                />
              </InputAdornment>
              {errors[column.field] && (
                <p className="text-[10px] font-semibold text-destructive">{errors[column.field]}</p>
              )}
            </div>
          ) : (
            _formatCell(lane, column)
          )}
        </TableCell>
      ))}
      <TableCell>
        <input
          type="checkbox"
          checked={lane.is_active}
          disabled={!canEdit || saving || draft !== null}
          onChange={(e) => toggleActive(e.target.checked)}
          aria-label={`Active: ${lane.origin_zone} to ${lane.dest_zone} by ${lane.transporter_name}`}
          data-testid={`${testId}.active`}
          className="h-4 w-4 rounded border-slate-300 accent-primary"
        />
      </TableCell>
      {canEdit && (
        <TableCell className="whitespace-nowrap text-right">
          {draft ? (
            <div className="flex justify-end gap-1">
              <Button
                type="button"
                size="sm"
                disabled={saving}
                onClick={save}
                aria-label="Save lane"
                data-testid={`${testId}.save`}
              >
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={cancel}
                aria-label="Cancel edit"
                data-testid={`${testId}.cancel`}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={saving}
              onClick={() => setDraft(laneToDraft(lane))}
              data-testid={`${testId}.edit`}
            >
              <Pencil className="mr-1.5 h-3.5 w-3.5" />
              Edit
            </Button>
          )}
        </TableCell>
      )}
    </TableRow>
  );
}
