// frontend/src/components/ui/icon-select.tsx
"use client";

import * as React from "react";
import { Inbox } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { OPTION_TONE_CLASSES, type OptionMeta, type SelectOption } from "@/lib/form-options";
import { cn } from "@/lib/utils";

/** Tile size used inside the trigger (`sm`) and inside list rows (`md`). */
type TileSize = "sm" | "md";

const TILE_SIZE_CLASSES: Readonly<Record<TileSize, string>> = {
  sm: "size-5 rounded-[5px]",
  md: "size-7 rounded-md",
};

const TILE_ICON_CLASSES: Readonly<Record<TileSize, string>> = {
  sm: "size-3",
  md: "size-3.5",
};

const TRIGGER_SIZE_CLASSES = {
  sm: "h-8 text-xs",
  default: "h-9 text-xs",
} as const;

interface OptionIconTileProps {
  option: Pick<OptionMeta, "icon" | "tone">;
  size?: TileSize;
  className?: string;
}

/**
 * Renders an option's lucide icon inside a softly tinted square tile.
 *
 * The icon carries explicit `size-*` and `text-current` classes so the
 * shadcn Select descendant rules (`[&_svg:not([class*='size-'])]` and
 * `[&_svg:not([class*='text-'])]`) never override the tile tint.
 *
 * @param option - Icon and tone to render.
 * @param size - `sm` for triggers and inline chips, `md` for list rows.
 * @param className - Extra classes for the tile wrapper.
 */
export function OptionIconTile({ option, size = "md", className }: OptionIconTileProps) {
  const Icon = option.icon;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 items-center justify-center",
        TILE_SIZE_CLASSES[size],
        OPTION_TONE_CLASSES[option.tone],
        className,
      )}
    >
      <Icon className={cn(TILE_ICON_CLASSES[size], "text-current")} strokeWidth={2.25} />
    </span>
  );
}

export interface IconSelectProps<TValue extends string> {
  /** Options to render, typically built with `toOptions(MAP)` from `lib/form-options`. */
  options: readonly SelectOption<TValue>[];
  /**
   * Current value (controlled mode). Empty string or `null` show the placeholder.
   * Leave `undefined` for uncontrolled mode, where the component tracks the
   * selection itself (used by fire-and-forget pickers such as doc type).
   */
  value?: string | null;
  /** Called with the selected option value. */
  onValueChange: (value: TValue) => void;
  /** Text shown when nothing is selected. */
  placeholder?: string;
  /** Message rendered inside the dropdown when `options` is empty. */
  emptyMessage?: string;
  /** Show one-line helper text under each option label (default `true`). */
  showDescriptions?: boolean;
  /** Show the icon tile inside the trigger (default `true`; disable for narrow unit pickers). */
  showTriggerIcon?: boolean;
  /** Trigger height preset. */
  size?: "sm" | "default";
  disabled?: boolean;
  name?: string;
  /** Applied to the trigger button (pass through from `FormControl`). */
  id?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "true" | "false";
  triggerClassName?: string;
  contentClassName?: string;
  ref?: React.Ref<HTMLButtonElement>;
  "data-testid"?: string;
}

/**
 * Dropdown that renders an icon tile + friendly label in the trigger and an
 * icon tile + label + helper text in every list row.
 *
 * Built on the shadcn/Radix `Select`, so it keeps full keyboard support
 * (arrow keys, typeahead via `textValue`, Escape) and screen-reader semantics
 * (`combobox` trigger, `listbox` content, labelled options).
 *
 * Works inside react-hook-form: wrap it in `<FormControl>` and the Slot
 * forwards `id`, `aria-describedby` and `aria-invalid` to the trigger.
 *
 * Spring Boot analogy: a Thymeleaf fragment that renders `th:each` over an
 * enum with its `messages.properties` label, reusable across every view.
 */
export function IconSelect<TValue extends string>({
  options,
  value,
  onValueChange,
  placeholder = "Select an option",
  emptyMessage = "No options available",
  showDescriptions = true,
  showTriggerIcon = true,
  size = "default",
  disabled,
  name,
  id,
  "aria-label": ariaLabel,
  "aria-describedby": ariaDescribedBy,
  "aria-invalid": ariaInvalid,
  triggerClassName,
  contentClassName,
  ref,
  "data-testid": dataTestId,
}: IconSelectProps<TValue>) {
  const [uncontrolledValue, setUncontrolledValue] = React.useState<string>("");
  const isControlled = value !== undefined;
  const currentValue = isControlled ? (value ?? "") : uncontrolledValue;
  const selected = options.find((option) => option.value === currentValue);

  /** Mirrors the selection locally in uncontrolled mode, then notifies the caller. */
  const handleValueChange = (next: string): void => {
    if (!isControlled) {
      setUncontrolledValue(next);
    }
    onValueChange(next as TValue);
  };

  return (
    <Select
      value={currentValue}
      onValueChange={handleValueChange}
      disabled={disabled}
      name={name}
    >
      <SelectTrigger
        ref={ref}
        id={id}
        data-testid={dataTestId}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        aria-invalid={ariaInvalid}
        className={cn(
          "w-full min-w-0 overflow-hidden bg-white font-medium text-slate-900",
          TRIGGER_SIZE_CLASSES[size],
          triggerClassName,
        )}
      >
        <SelectValue placeholder={placeholder}>
          {selected ? (
            <span className="flex min-w-0 items-center gap-2">
              {showTriggerIcon && <OptionIconTile option={selected} size="sm" />}
              <span className="truncate">{selected.label}</span>
            </span>
          ) : undefined}
        </SelectValue>
      </SelectTrigger>
      <SelectContent
        position="popper"
        sideOffset={4}
        className={cn(
          "max-h-80 min-w-[var(--radix-select-trigger-width)] max-w-[min(26rem,calc(100vw-2rem))]",
          contentClassName,
        )}
      >
        {options.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 px-3 py-5 text-center text-xs text-slate-500">
            <Inbox className="size-4 text-slate-400" aria-hidden="true" />
            <span>{emptyMessage}</span>
          </div>
        ) : (
          options.map((option) => (
            <SelectItem
              key={option.value}
              value={option.value}
              textValue={option.label}
              className="cursor-pointer py-2 pr-8 pl-2"
            >
              <span className="flex min-w-0 items-center gap-2.5">
                <OptionIconTile option={option} size="md" />
                <span className="flex min-w-0 flex-col text-left">
                  <span className="truncate text-xs font-semibold text-slate-900">
                    {option.label}
                  </span>
                  {showDescriptions && (
                    <span className="truncate text-[11px] leading-snug font-normal text-slate-500">
                      {option.description}
                    </span>
                  )}
                </span>
              </span>
            </SelectItem>
          ))
        )}
      </SelectContent>
    </Select>
  );
}
