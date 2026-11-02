import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { format } from "date-fns"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Helper to format Pickup Time Slot to 12HR format
export const formatTimeSlot = (slot: string) => {
  const mapping: Record<string, string> = {
    "06:00 - 10:00": "06:00 AM - 10:00 AM",
    "10:00 - 14:00": "10:00 AM - 02:00 PM",
    "14:00 - 18:00": "02:00 PM - 06:00 PM",
    "18:00 - 22:00": "06:00 PM - 10:00 PM",
  };
  return mapping[slot] || slot;
};

/** Indian Standard Time zone and locale used across all courier timestamps (F-02). */
export const IST_TIME_ZONE = "Asia/Kolkata";
export const IST_LOCALE = "en-IN";

/** Matches a calendar-date-only string (`YYYY-MM-DD`). */
const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
/** Matches an ISO datetime that already carries `Z` or a `±HH:MM` / `±HHMM` offset. */
const EXPLICIT_TZ_OFFSET_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;
/** Lookup table mapping 1-based month (`1..12`) to 0-based JS `Date` month (`0..11`). */
const ZERO_BASED_MONTH = [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] as const;

const IST_WALL_CLOCK_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  timeZone: IST_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/**
 * Parses a backend timestamp or date string into a `Date`, treating naive ISO
 * datetime strings (e.g. `"2026-10-29T20:00:00"` or `"2026-10-29 20:00:00"`,
 * which FastAPI serialises from UTC `TIMESTAMP WITHOUT TIME ZONE` columns) as
 * UTC rather than the browser's local timezone (F-02).
 *
 * Calendar-date-only strings (`"2026-10-30"`) are anchored at midnight IST
 * (`+05:30`) so formatting them in `Asia/Kolkata` preserves the exact date.
 *
 * @param value - ISO string, `Date`, or nullish value.
 * @returns A valid `Date`, or `null` when the input is empty or unparseable.
 */
export function parseUtcDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) {
    return isNaN(value.getTime()) ? null : value;
  }
  const trimmed = value.trim();
  if (!trimmed) return null;
  let normalized = trimmed;
  if (DATE_ONLY_PATTERN.test(trimmed)) {
    normalized = `${trimmed}T00:00:00+05:30`;
  } else {
    const isoLike = trimmed.includes("T") ? trimmed : trimmed.replace(" ", "T");
    if (isoLike.includes("T") && !EXPLICIT_TZ_OFFSET_PATTERN.test(isoLike)) {
      normalized = `${isoLike}Z`;
    } else {
      normalized = isoLike;
    }
  }
  const parsed = new Date(normalized);
  return isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Converts an instant into a `Date` whose local wall-clock fields equal the
 * `Asia/Kolkata` (IST) wall-clock fields of `instant`, so `date-fns` `format()`
 * produces IST output regardless of the host machine's timezone.
 */
function _toIstWallClockDate(instant: Date): Date {
  const parts: Record<string, number> = {};
  for (const part of IST_WALL_CLOCK_FORMATTER.formatToParts(instant)) {
    if (part.type !== "literal") {
      parts[part.type] = Number(part.value);
    }
  }
  const hour = parts.hour === 24 ? 0 : (parts.hour ?? 0);
  const monthIndex = ZERO_BASED_MONTH[parts.month ?? 1] ?? 0;
  return new Date(
    parts.year ?? 1970,
    monthIndex,
    parts.day ?? 1,
    hour,
    parts.minute ?? 0,
    parts.second ?? 0,
  );
}

export const safeFormatDate = (
  dateStr: string | null | undefined,
  formatStr: string = "dd MMM yyyy"
): string => {
  if (!dateStr) return "-";
  try {
    const parsed = parseUtcDate(dateStr);
    if (!parsed) return "-";
    return format(_toIstWallClockDate(parsed), formatStr);
  } catch {
    return "-";
  }
};

/**
 * Formats an API date/datetime string in `en-IN` / `Asia/Kolkata` (IST),
 * treating naive ISO datetime strings as UTC (F-02).
 */
export function formatIstDate(
  dateStr: string | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    day: "2-digit",
    month: "short",
    year: "numeric",
  },
  fallback: string = "—",
): string {
  const parsed = parseUtcDate(dateStr);
  if (!parsed) return fallback;
  return parsed.toLocaleDateString(IST_LOCALE, {
    ...options,
    timeZone: IST_TIME_ZONE,
  });
}

/**
 * Formats an API datetime string with date + time in `en-IN` / `Asia/Kolkata`
 * (IST), treating naive ISO datetime strings as UTC (F-02).
 */
export function formatIstDateTime(
  dateStr: string | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  },
  fallback: string = "—",
): string {
  const parsed = parseUtcDate(dateStr);
  if (!parsed) return fallback;
  return parsed.toLocaleString(IST_LOCALE, {
    ...options,
    timeZone: IST_TIME_ZONE,
  });
}

const IST_OFFSET_SUFFIX = "+05:30";
const MINUTE_ONLY_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/**
 * Converts a local IST datetime input (e.g. `"2026-10-20T10:00"` from
 * `<input type="datetime-local">` or `date + slot` in IST) into an explicit
 * UTC ISO-8601 timestamp (`...Z`) interpreted from `Asia/Kolkata` (+05:30),
 * so the backend never treats an IST appointment window as UTC (D-09).
 */
export function toIstIsoString(
  dateTimeInput: string | null | undefined,
): string | undefined {
  if (!dateTimeInput) return undefined;
  const trimmed = dateTimeInput.trim();
  if (!trimmed) return undefined;
  if (EXPLICIT_TZ_OFFSET_PATTERN.test(trimmed)) {
    const parsed = new Date(trimmed);
    return isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
  }
  const isoWithSeconds = MINUTE_ONLY_DATETIME_PATTERN.test(trimmed)
    ? `${trimmed}:00`
    : trimmed;
  const parsed = new Date(`${isoWithSeconds}${IST_OFFSET_SUFFIX}`);
  return isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

/**
 * Formats an API ISO timestamp (or local `datetime-local` string) into the
 * `"YYYY-MM-DDTHH:mm"` string expected by `<input type="datetime-local">` in
 * `Asia/Kolkata` (IST) wall-clock time (D-09).
 */
export function toIstDateTimeLocalValue(
  dateTimeInput: string | null | undefined,
): string {
  if (!dateTimeInput) return "";
  const trimmed = dateTimeInput.trim();
  if (!trimmed) return "";
  if (!EXPLICIT_TZ_OFFSET_PATTERN.test(trimmed)) {
    return trimmed.slice(0, 16);
  }
  const parsed = new Date(trimmed);
  if (isNaN(parsed.getTime())) return "";
  return format(_toIstWallClockDate(parsed), "yyyy-MM-dd'T'HH:mm");
}

/** FastAPI `loc` roots that are not field names (`["body", "packages", 0, "weight"]`). */
const VALIDATION_LOC_ROOTS: ReadonlySet<string> = new Set(["body", "query", "path", "header", "cookie"]);
/** Prefix Pydantic adds to messages raised by custom validators. */
const PYDANTIC_VALUE_ERROR_PREFIX = /^Value error,\s*/i;

/** One FastAPI/Pydantic validation error item (`detail[]` of a 422). */
interface ValidationErrorItem {
  loc?: unknown;
  msg?: unknown;
}

/**
 * Turns a FastAPI `loc` path into a readable field name
 * (`["body", "delivery_address", "pincode"]` → "Delivery address › Pincode",
 * `["body", "packages", 0, "weight"]` → "Packages #1 › Weight").
 *
 * @param loc - The raw `loc` array.
 * @returns The field label, or "" when there is no field part.
 */
export function formatValidationLocation(loc: unknown): string {
  if (!Array.isArray(loc)) return "";
  const parts: string[] = [];
  loc.forEach((segment, index) => {
    if (index === 0 && typeof segment === "string" && VALIDATION_LOC_ROOTS.has(segment)) return;
    if (typeof segment === "number") {
      if (parts.length > 0) parts[parts.length - 1] += ` #${segment + 1}`;
      return;
    }
    if (typeof segment !== "string" || !segment) return;
    const words = segment.replace(/_/g, " ").trim();
    parts.push(words.charAt(0).toUpperCase() + words.slice(1));
  });
  return parts.join(" › ");
}

/**
 * Formats one validation item as "Field: message" (or just the message).
 *
 * @param item - A `detail[]` entry, or a plain string.
 * @returns Readable text, or null when the item carries no message.
 */
function _formatValidationItem(item: ValidationErrorItem | string): string | null {
  if (typeof item === "string") return item.trim() || null;
  if (!item || typeof item.msg !== "string" || !item.msg.trim()) return null;
  const message = item.msg.replace(PYDANTIC_VALUE_ERROR_PREFIX, "").trim();
  const field = formatValidationLocation(item.loc);
  return field ? `${field}: ${message}` : message;
}

/**
 * The ONE way to turn any API failure into toast/inline text (F-08). It always
 * returns a plain string, so a 422 `detail` array/object can never reach a
 * toast and crash rendering. 422s name the field: "Packages #1 › Weight: …".
 *
 * Accepts generated-client `ApiError`s (`err.body.detail`), raw axios errors
 * (`err.response.data.detail`) and plain `Error`s.
 *
 * @param err - Whatever was thrown.
 * @param fallback - Text used when nothing readable is found.
 * @returns A non-empty, human-readable message.
 */
export const extractApiErrorMessage = (
  err: unknown,
  fallback: string = "Something went wrong. Please try again."
): string => {
  const apiErr = err as {
    body?: { detail?: unknown };
    response?: { data?: { detail?: unknown } };
    message?: string;
  } | null;
  const detail = apiErr?.body?.detail ?? apiErr?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail
      .map((item) => _formatValidationItem(item as ValidationErrorItem | string))
      .filter((text): text is string => Boolean(text));
    if (messages.length === 1) return messages[0];
    if (messages.length > 1) return `${messages[0]} (+${messages.length - 1} more)`;
  }
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const nested = (detail as { message?: unknown; detail?: unknown });
    const text = typeof nested.message === "string" ? nested.message : nested.detail;
    if (typeof text === "string" && text.trim()) return text;
  }
  if (typeof apiErr?.message === "string" && apiErr.message.trim()) {
    return apiErr.message;
  }
  return fallback;
};

