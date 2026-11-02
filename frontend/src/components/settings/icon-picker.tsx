// frontend/src/components/settings/icon-picker.tsx
"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  getServiceIconMeta,
  SERVICE_ICON_REGISTRY,
  type ServiceIconKey,
} from "@/lib/icon-registry";
import { cn } from "@/lib/utils";
import { Check, ChevronDown, HelpCircle, Search } from "lucide-react";
import { useMemo, useState } from "react";

interface IconPickerProps {
  value: string | null | undefined;
  onChange: (nextKey: ServiceIconKey) => void;
  disabled?: boolean;
}

/**
 * Visual icon selector for Service cards in Platform Settings.
 * Replaces free-text Lucide icon name inputs so admins pick from a curated
 * gallery of logistics icons that always render on the public Services page.
 */
export function IconPicker({ value, onChange, disabled = false }: IconPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const currentMeta = getServiceIconMeta(value);
  const CurrentIcon = currentMeta ? currentMeta.icon : HelpCircle;

  const filteredIcons = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SERVICE_ICON_REGISTRY;
    return SERVICE_ICON_REGISTRY.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q) ||
        item.key.includes(q) ||
        item.keywords.some((kw) => kw.includes(q)),
    );
  }, [query]);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        disabled={disabled}
        onClick={() => setOpen(true)}
        className="h-10 w-full justify-between bg-white px-3 font-normal text-slate-900 hover:bg-slate-50"
      >
        <span className="flex items-center gap-2.5 truncate">
          <span
            className={cn(
              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border",
              currentMeta
                ? "border-primary/20 bg-primary/10 text-primary"
                : "border-amber-200 bg-amber-50 text-amber-700",
            )}
          >
            <CurrentIcon className="h-4 w-4" aria-hidden />
          </span>
          <span className="truncate text-left text-xs font-semibold">
            {currentMeta ? currentMeta.label : "Choose an icon"}
          </span>
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Choose a Service Icon</DialogTitle>
            <DialogDescription>
              Select an icon for this service card. Every icon below is verified to display on your public Services page.
            </DialogDescription>
          </DialogHeader>

          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search icons (e.g. truck, air, warehouse, returns, cold chain)"
              className="pl-9"
            />
          </div>

          <div className="grid max-h-[360px] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2 md:grid-cols-3">
            {filteredIcons.map((item) => {
              const Icon = item.icon;
              const isSelected = currentMeta?.key === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => {
                    onChange(item.key);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex items-start gap-3 rounded-xl border p-3 text-left transition-all hover:border-primary/40 hover:bg-primary/5",
                    isSelected
                      ? "border-primary bg-primary/10 ring-1 ring-primary"
                      : "border-slate-200 bg-white",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                      isSelected
                        ? "bg-primary text-primary-foreground"
                        : "bg-slate-100 text-slate-700",
                    )}
                  >
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-1">
                      <span className="truncate text-xs font-bold text-slate-900">
                        {item.label}
                      </span>
                      {isSelected && (
                        <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
                      )}
                    </span>
                    <span className="mt-0.5 line-clamp-2 block text-[11px] leading-snug text-slate-500">
                      {item.description}
                    </span>
                  </span>
                </button>
              );
            })}
            {filteredIcons.length === 0 && (
              <p className="col-span-full py-8 text-center text-sm text-slate-500">
                No matching icons found. Try searching for &ldquo;truck&rdquo;, &ldquo;air&rdquo;, or &ldquo;warehouse&rdquo;.
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
