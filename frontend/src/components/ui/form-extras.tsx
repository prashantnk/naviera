// frontend/src/components/ui/form-extras.tsx
import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Rose asterisk that marks a field as required.
 *
 * Hidden from assistive tech because required-ness is already conveyed by
 * the zod error message; the visual mark only aids sighted scanning.
 */
export function RequiredMark({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn("ml-0.5 font-bold text-rose-500", className)}>
      *
    </span>
  );
}

interface FormSectionProps {
  /** Lucide icon shown in the tinted header tile. */
  icon: LucideIcon;
  /** Section title (sentence case). */
  title: string;
  /** Optional one-line subtitle under the title. */
  description?: string;
  /** Optional element aligned to the right of the header (badge, action). */
  action?: React.ReactNode;
  className?: string;
  /** Classes for the body wrapper that holds the fields. */
  bodyClassName?: string;
  children: React.ReactNode;
}

/**
 * Titled group of related fields with an icon header, used to give every
 * dialog and wizard the same Delhivery One style section rhythm.
 *
 * @param icon - Header icon.
 * @param title - Section title.
 * @param description - Optional helper subtitle.
 * @param action - Optional right-aligned header slot.
 */
export function FormSection({
  icon: Icon,
  title,
  description,
  action,
  className,
  bodyClassName,
  children,
}: FormSectionProps) {
  return (
    <section className={cn("space-y-3", className)}>
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            aria-hidden="true"
            className="bg-primary/10 text-primary mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-md"
          >
            <Icon className="size-3.5" />
          </span>
          <div className="min-w-0">
            <h4 className="text-sm leading-tight font-semibold text-slate-900">{title}</h4>
            {description && (
              <p className="mt-0.5 text-xs leading-snug text-slate-500">{description}</p>
            )}
          </div>
        </div>
        {action}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

interface InputAdornmentProps {
  /** Text or node rendered inside the left edge (e.g. `₹`). */
  prefix?: React.ReactNode;
  /** Text or node rendered inside the right edge (e.g. `kg`, `cm`, `%`). */
  suffix?: React.ReactNode;
  className?: string;
  /** Exactly one input (usually wrapped in `FormControl`). */
  children: React.ReactNode;
}

/**
 * Wraps an input and overlays non-interactive unit adornments inside it.
 *
 * Padding is added to the nested `input` through descendant selectors so the
 * wrapped `<Input {fieldProps} />` stays untouched (no prop changes, no
 * behaviour change).
 *
 * @param prefix - Leading adornment such as the rupee sign.
 * @param suffix - Trailing unit such as kg or cm.
 */
export function InputAdornment({ prefix, suffix, className, children }: InputAdornmentProps) {
  return (
    <div
      className={cn(
        "relative w-full min-w-0",
        prefix ? "[&_input]:pl-7" : undefined,
        suffix ? "[&_input]:pr-10" : undefined,
        className,
      )}
    >
      {children}
      {prefix && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2.5 text-xs font-semibold text-slate-400"
        >
          {prefix}
        </span>
      )}
      {suffix && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase"
        >
          {suffix}
        </span>
      )}
    </div>
  );
}
