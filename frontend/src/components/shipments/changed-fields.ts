// frontend/src/components/shipments/changed-fields.ts
/**
 * "Send only what changed" helpers for the shipment edit pages (plan B14).
 *
 * The edit pages keep a snapshot of the values they loaded. On save they diff the
 * current form values against that snapshot and send only the keys that differ, so
 * the backend re-prices a shipment only when a real price input changed (fixes R1:
 * an address-only fix no longer re-prices a COD + "add shipping" order).
 *
 * Spring analogy: a JSON Merge Patch (RFC 7386) builder: absent key = "leave as is".
 */

/** Plain JSON-like record. */
export type PlainRecord = Record<string, unknown>;

/**
 * Normalises a form value for comparison: empty string, null and undefined all mean "no value".
 *
 * @param value - Any form value.
 * @returns A canonical value whose JSON form is stable (object keys sorted).
 */
function _normalise(value: unknown): unknown {
  if (value === undefined || value === null || value === "") return null;
  if (Array.isArray(value)) return value.map(_normalise);
  if (typeof value === "object") {
    const record = value as PlainRecord;
    return Object.keys(record)
      .sort()
      .reduce<PlainRecord>((acc, key) => {
        acc[key] = _normalise(record[key]);
        return acc;
      }, {});
  }
  return value;
}

/**
 * Deep equality that treats "", null and undefined as the same empty value.
 *
 * @param left - First value.
 * @param right - Second value.
 * @returns True when both values carry the same data.
 */
export function isSameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(_normalise(left)) === JSON.stringify(_normalise(right));
}

/**
 * Returns the keys of `current` (limited to `keys`) whose value differs from `initial`.
 *
 * @param initial - Snapshot taken when the form was loaded.
 * @param current - Values at submit time.
 * @param keys - Keys to compare.
 * @returns The changed keys, in the order given.
 */
export function changedKeys<T extends PlainRecord>(
  initial: T,
  current: T,
  keys: readonly (keyof T)[],
): (keyof T)[] {
  return keys.filter((key) => !isSameValue(initial[key], current[key]));
}

/**
 * Builds a partial object holding only the changed keys.
 *
 * @param initial - Snapshot taken when the form was loaded.
 * @param current - Values at submit time.
 * @param keys - Keys that may be sent.
 * @returns A partial object (empty when nothing changed).
 */
export function pickChanged<T extends PlainRecord>(
  initial: T,
  current: T,
  keys: readonly (keyof T)[],
): Partial<T> {
  return changedKeys(initial, current, keys).reduce<Partial<T>>((acc, key) => {
    acc[key] = current[key];
    return acc;
  }, {});
}

/**
 * True when the partial object carries at least one key.
 *
 * @param partial - Output of `pickChanged`.
 * @returns Whether anything changed.
 */
export function hasChanges(partial: PlainRecord | null | undefined): boolean {
  return partial !== null && partial !== undefined && Object.keys(partial).length > 0;
}
