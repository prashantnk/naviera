// frontend/src/components/shipments/use-edit-package-testids.ts
"use client";

/**
 * Stamps `data-testid="shipment-edit.form.<field>-<index>"` on package inputs inside the
 * B2C and B2B edit forms (e.g. `shipment-edit.form.weight-0`), matching `ShipmentEditIds`
 * in `backend/scripts/tests/ui_golden/testids.py` without modifying shared booking components.
 */
import { useEffect, type RefObject } from "react";

const PACKAGE_INPUT_NAME_RE = /^packages\.(\d+)\.([a-z_]+)$/;

/**
 * Stamps `data-testid` attributes on all `input[name^="packages."]` elements inside `root`.
 *
 * @param root - Form container element.
 * @param testIdPage - Page prefix (`shipment-edit` by default).
 */
function _stampPackageInputTestIds(root: HTMLElement, testIdPage: string): void {
  const inputs = root.querySelectorAll<HTMLInputElement>('input[name^="packages."]');
  inputs.forEach((input) => {
    const match = PACKAGE_INPUT_NAME_RE.exec(input.name);
    if (!match) return;
    const [, index, rawField] = match;
    const fieldSlug = rawField.replace(/_/g, "-");
    const expected = `${testIdPage}.form.${fieldSlug}-${index}`;
    if (input.getAttribute("data-testid") !== expected) {
      input.setAttribute("data-testid", expected);
    }
  });
}

/**
 * Keeps `data-testid="<testIdPage>.form.<field>-<index>"` attached to package inputs inside `containerRef`.
 *
 * @param containerRef - Ref attached to the `<form>` or wrapper element.
 * @param active - Whether the form has finished loading and is mounted.
 * @param testIdPage - Page prefix (`shipment-edit` by default).
 */
export function useEditPackageTestIds(
  containerRef: RefObject<HTMLElement | null>,
  active: boolean,
  testIdPage = "shipment-edit",
): void {
  useEffect(() => {
    const el = containerRef.current;
    if (!active || !el) return;

    _stampPackageInputTestIds(el, testIdPage);
    const observer = new MutationObserver(() => {
      _stampPackageInputTestIds(el, testIdPage);
    });
    observer.observe(el, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [containerRef, active, testIdPage]);
}
