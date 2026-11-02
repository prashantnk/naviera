// frontend/src/components/settings/string-list-editor.tsx
"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";

interface ChipListInputProps {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  addLabel?: string;
  validateItem?: (candidate: string) => string | null;
}

/**
 * Structured chip list input (for phone numbers and email addresses) so admins
 * add and remove validated items individually instead of editing comma-separated strings.
 */
export function ChipListInput({
  values,
  onChange,
  placeholder,
  addLabel = "Add",
  validateItem,
}: ChipListInputProps) {
  const [draft, setDraft] = useState("");
  const [errorText, setErrorText] = useState<string | null>(null);

  const handleAdd = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (validateItem) {
      const validationError = validateItem(trimmed);
      if (validationError) {
        setErrorText(validationError);
        return;
      }
    }
    if (values.includes(trimmed)) {
      setErrorText("Already added.");
      return;
    }
    onChange(values.concat([trimmed]));
    setDraft("");
    setErrorText(null);
  };

  const handleRemove = (index: number) => {
    onChange(values.filter((_, idx) => idx !== index));
  };

  return (
    <div className="space-y-2 min-w-0">
      <div className="flex gap-2 min-w-0">
        <Input
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            if (errorText) setErrorText(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAdd();
            }
          }}
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-white text-sm"
        />
        <Button type="button" variant="outline" onClick={handleAdd} className="shrink-0">
          <Plus className="mr-1.5 h-4 w-4" />
          {addLabel}
        </Button>
      </div>
      {errorText && <p className="text-xs font-medium text-rose-600">{errorText}</p>}
      {values.length > 0 ? (
        <div className="flex flex-wrap gap-2 pt-1">
          {values.map((item, idx) => (
            <span
              key={`${item}-${idx}`}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-800"
            >
              <span>{item}</span>
              <button
                type="button"
                onClick={() => handleRemove(idx)}
                aria-label={`Remove ${item}`}
                className="rounded-full p-0.5 text-slate-500 hover:bg-slate-200 hover:text-slate-900"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-400">No items added yet.</p>
      )}
    </div>
  );
}

interface OrderedTextListEditorProps {
  items: string[];
  onChange: (next: string[]) => void;
  addButtonLabel: string;
  itemLabel: string;
  placeholder: string;
  multiline?: boolean;
  maxLength?: number;
}

/**
 * Structured list editor with add, remove, reorder and character counter
 * (replaces newline-delimited or blank-line-delimited textareas).
 */
export function OrderedTextListEditor({
  items,
  onChange,
  addButtonLabel,
  itemLabel,
  placeholder,
  multiline = false,
  maxLength = 1000,
}: OrderedTextListEditorProps) {
  const updateAt = (index: number, nextValue: string) => {
    const copy = items.slice();
    copy[index] = nextValue;
    onChange(copy);
  };

  const removeAt = (index: number) => {
    onChange(items.filter((_, idx) => idx !== index));
  };

  const moveItem = (index: number, direction: "up" | "down") => {
    const targetIdx = direction === "up" ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= items.length) return;
    const copy = items.slice();
    const current = copy[index];
    copy[index] = copy[targetIdx];
    copy[targetIdx] = current;
    onChange(copy);
  };

  return (
    <div className="space-y-3 min-w-0">
      {items.map((item, idx) => (
        <div
          key={idx}
          className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-50/70 p-3 space-y-2"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
            <span className="text-xs font-bold text-slate-600">
              {itemLabel} #{idx + 1}
            </span>
            <div className="flex items-center gap-1">
              <span className="mr-2 text-[11px] font-mono text-slate-400">
                {item.length} / {maxLength}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={idx === 0}
                onClick={() => moveItem(idx, "up")}
                aria-label={`Move ${itemLabel} ${idx + 1} up`}
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={idx === items.length - 1}
                onClick={() => moveItem(idx, "down")}
                aria-label={`Move ${itemLabel} ${idx + 1} down`}
              >
                <ArrowDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
                onClick={() => removeAt(idx)}
                aria-label={`Remove ${itemLabel} ${idx + 1}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
          {multiline ? (
            <Textarea
              value={item}
              maxLength={maxLength}
              onChange={(e) => updateAt(idx, e.target.value)}
              placeholder={placeholder}
              className="min-w-0 w-full bg-white h-20 text-sm"
            />
          ) : (
            <Input
              value={item}
              maxLength={maxLength}
              onChange={(e) => updateAt(idx, e.target.value)}
              placeholder={placeholder}
              className="min-w-0 w-full bg-white text-sm"
            />
          )}
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        onClick={() => onChange(items.concat([""]))}
        className="w-full border-dashed bg-white"
      >
        <Plus className="mr-2 h-4 w-4" />
        {addButtonLabel}
      </Button>
    </div>
  );
}
