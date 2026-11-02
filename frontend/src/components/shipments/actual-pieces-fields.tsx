// frontend/src/components/shipments/actual-pieces-fields.tsx
"use client";

/**
 * "Actual pieces" grid: one row per box size the rider / hub actually found
 * (number of boxes, L × B × H with unit, weight per box). Used by the pickup dispatch
 * dialog (B5) and the Record measurement dialog (B4). Inputs only: the backend works
 * out the chargeable weight and the new bill.
 *
 * Phone first: each row is a small card (2 columns on a 390 px screen, one line on
 * desktop), with large touch targets.
 */
import { Plus, Trash2 } from "lucide-react";
import {
  useFieldArray,
  type ArrayPath,
  type Control,
  type FieldArray,
  type FieldValues,
  type Path,
} from "react-hook-form";
import * as z from "zod";

import { DimensionUnit, WeightUnit, type PackageCreate } from "@/api_client";
import { Button } from "@/components/ui/button";
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Dimension units offered for field measurements (short labels for small screens). */
const DIMENSION_UNIT_LABELS: Readonly<Record<DimensionUnit, string>> = {
  [DimensionUnit.CM]: "cm",
  [DimensionUnit.M]: "m",
  [DimensionUnit.IN]: "in",
  [DimensionUnit.FT]: "ft",
};

/** Validation for one box size. */
export const pieceSchema = z.object({
  box_count: z.number({ message: "Enter boxes" }).int("Whole boxes only").min(1, "At least 1 box"),
  length: z.number({ message: "Enter length" }).positive("Enter length"),
  breadth: z.number({ message: "Enter breadth" }).positive("Enter breadth"),
  height: z.number({ message: "Enter height" }).positive("Enter height"),
  dimension_unit: z.nativeEnum(DimensionUnit),
  weight: z.number({ message: "Enter weight" }).positive("Enter weight per box"),
});

/** Form values of one box size. */
export type PieceValues = z.infer<typeof pieceSchema>;

/** A fresh, empty row (rider fills it in). */
export function emptyPiece(): PieceValues {
  return {
    box_count: 1,
    length: undefined as unknown as number,
    breadth: undefined as unknown as number,
    height: undefined as unknown as number,
    dimension_unit: DimensionUnit.CM,
    weight: undefined as unknown as number,
  };
}

/**
 * Maps form rows to the API package shape (weight is always captured in kg).
 *
 * @param pieces - Validated rows.
 * @returns `PackageCreate[]` for the measurements / dispatch payload.
 */
export function piecesToPackages(pieces: readonly PieceValues[]): PackageCreate[] {
  return pieces.map((piece) => ({
    box_count: piece.box_count,
    length: piece.length,
    breadth: piece.breadth,
    height: piece.height,
    dimension_unit: piece.dimension_unit,
    weight: piece.weight,
    weight_unit: WeightUnit.KG,
  }));
}

/**
 * Converts an `<input type="number">` value for RHF (empty stays undefined so zod reports it).
 *
 * @param raw - The input's string value.
 * @returns Parsed number or undefined.
 */
function _numberOrUndefined(raw: string): number | undefined {
  return raw === "" ? undefined : Number(raw);
}

/** Props of {@link ActualPiecesFields}. */
export interface ActualPiecesFieldsProps<TFieldValues extends FieldValues> {
  control: Control<TFieldValues>;
  /** Path of the `PieceValues[]` array inside the form. */
  name: ArrayPath<TFieldValues>;
  /** `data-testid` prefix, e.g. `pickup-dispatch.row.<awb>.actual-pieces`. */
  testIdPrefix: string;
  /** When true, row 0 uses `<testIdPrefix>.<field>` (e.g. `measurement.form.weight`). */
  flatFirstRowTestIds?: boolean;
  disabled?: boolean;
}

/** Editable list of box sizes with add / remove. */
export function ActualPiecesFields<TFieldValues extends FieldValues>({
  control,
  name,
  testIdPrefix,
  flatFirstRowTestIds = false,
  disabled = false,
}: ActualPiecesFieldsProps<TFieldValues>) {
  const { fields, append, remove } = useFieldArray({ control, name });
  const fieldPath = (index: number, key: keyof PieceValues) =>
    `${name}.${index}.${key}` as Path<TFieldValues>;
  const fieldTestId = (index: number, key: keyof PieceValues) => {
    const slug = key.replace("_", "-");
    return flatFirstRowTestIds && index === 0
      ? `${testIdPrefix}.${slug}`
      : `${testIdPrefix}.piece-${index}.${slug}`;
  };

  const numberField = (index: number, key: keyof PieceValues, label: string, step: string) => (
    <FormField
      control={control}
      name={fieldPath(index, key)}
      render={({ field }) => (
        <FormItem className="min-w-0 space-y-1">
          <FormLabel className="text-[11px] font-semibold text-muted-foreground">{label}</FormLabel>
          <FormControl>
            <Input
              type="number"
              inputMode="decimal"
              step={step}
              min="0"
              disabled={disabled}
              data-testid={fieldTestId(index, key)}
              value={field.value ?? ""}
              onChange={(event) => field.onChange(_numberOrUndefined(event.target.value))}
              onBlur={field.onBlur}
              className="h-10 min-w-0 w-full bg-background font-mono text-sm"
            />
          </FormControl>
          <FormMessage className="text-[11px]" />
        </FormItem>
      )}
    />
  );

  return (
    <div data-testid={testIdPrefix} className="min-w-0 space-y-2">
      {fields.map((row, index) => (
        <div
          key={row.id}
          data-testid={`${testIdPrefix}.piece-${index}`}
          className="min-w-0 overflow-hidden space-y-2 rounded-lg border border-border bg-muted/20 p-2.5"
        >
          <div className="flex items-center justify-between gap-2 min-w-0">
            <span className="text-xs font-semibold text-foreground">Box size {index + 1}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={disabled || fields.length === 1}
              onClick={() => remove(index)}
              aria-label="Remove this box size"
              data-testid={`${testIdPrefix}.piece-${index}.remove`}
              className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 items-end min-w-0">
            {numberField(index, "box_count", "Boxes", "1")}
            {numberField(index, "weight", "Kg per box", "0.01")}
            {numberField(index, "length", "Length", "0.1")}
            {numberField(index, "breadth", "Breadth", "0.1")}
            {numberField(index, "height", "Height", "0.1")}
            <FormField
              control={control}
              name={fieldPath(index, "dimension_unit")}
              render={({ field }) => (
                <FormItem className="min-w-0 space-y-1">
                  <FormLabel className="text-[11px] font-semibold text-muted-foreground">Unit</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange} disabled={disabled}>
                    <FormControl>
                      <SelectTrigger
                        data-testid={`${testIdPrefix}.piece-${index}.unit`}
                        className="h-10 min-w-0 w-full bg-background"
                      >
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {Object.values(DimensionUnit).map((unit) => (
                        <SelectItem key={unit} value={unit}>
                          {DIMENSION_UNIT_LABELS[unit]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormItem>
              )}
            />
          </div>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        data-testid={`${testIdPrefix}.add-piece`}
        onClick={() => append(emptyPiece() as FieldArray<TFieldValues, ArrayPath<TFieldValues>>)}
        className="h-9 w-full sm:w-auto"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        Add another box size
      </Button>
    </div>
  );
}
