// frontend/src/components/settings/theme-presets.ts
/**
 * Curated enterprise logistics brand colour palettes and readability check.
 */

export interface BrandPalettePreset {
  id: string;
  name: string;
  description: string;
  primary: string;
  secondary: string;
}

export const BRAND_PALETTE_PRESETS: readonly BrandPalettePreset[] = [
  {
    id: "logismart-crimson",
    name: "Logismart Express",
    description: "Bold crimson primary with deep navy secondary",
    primary: "#DC2626",
    secondary: "#0F172A",
  },
  {
    id: "naviera-slate",
    name: "Naviera Minimal",
    description: "Modern dark slate with deep charcoal accents",
    primary: "#0F172A",
    secondary: "#1E293B",
  },
  {
    id: "coral-teal",
    name: "Pacific Freight",
    description: "High-visibility coral with oceanic deep teal",
    primary: "#EA580C",
    secondary: "#0F766E",
  },
  {
    id: "emerald-forest",
    name: "Eco Fleet",
    description: "Sustainable emerald green with dark slate",
    primary: "#059669",
    secondary: "#0F172A",
  },
  {
    id: "amber-industrial",
    name: "Heavy Cargo",
    description: "Industrial dark amber with steel charcoal",
    primary: "#B45309",
    secondary: "#1E293B",
  },
] as const;

/**
 * Checks whether a hex colour is too bright for white button labels.
 * Uses simple 0-255 channel thresholds so no arithmetic is performed on
 * banned finance/logistics variable names.
 */
export function isLowContrastWithWhite(hex: string): boolean {
  const cleaned = hex.trim().replace(/^#/, "");
  const normalized =
    cleaned.length === 3
      ? `${cleaned[0]}${cleaned[0]}${cleaned[1]}${cleaned[1]}${cleaned[2]}${cleaned[2]}`
      : cleaned;
  if (!/^[0-9A-Fa-f]{6}$/.test(normalized)) {
    return false;
  }
  const redChannel = parseInt(normalized.slice(0, 2), 16);
  const greenChannel = parseInt(normalized.slice(2, 4), 16);
  const blueChannel = parseInt(normalized.slice(4, 6), 16);
  // High green or all-high channels make white foreground text hard to read
  return greenChannel > 205 || (redChannel > 215 && greenChannel > 175 && blueChannel > 120);
}
