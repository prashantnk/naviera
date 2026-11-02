// frontend/src/components/settings/theme-presets.test.ts
import { describe, expect, it } from "vitest";
import { BRAND_PALETTE_PRESETS, isLowContrastWithWhite } from "./theme-presets";

describe("theme-presets", () => {
  it("provides 5 high-contrast brand palettes", () => {
    expect(BRAND_PALETTE_PRESETS).toHaveLength(5);
    for (const preset of BRAND_PALETTE_PRESETS) {
      expect(preset.primary).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(preset.secondary).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(isLowContrastWithWhite(preset.primary)).toBe(false);
    }
  });

  it("flags bright colours as low-contrast against white text", () => {
    expect(isLowContrastWithWhite("#FFFF00")).toBe(true);
    expect(isLowContrastWithWhite("#E2E8F0")).toBe(true);
    expect(isLowContrastWithWhite("#0F172A")).toBe(false);
    expect(isLowContrastWithWhite("#DC2626")).toBe(false);
  });
});
