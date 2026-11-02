// frontend/src/lib/icon-registry.test.ts
import { describe, expect, it } from "vitest";
import {
  ALLOWED_ICON_KEYS,
  getServiceIconMeta,
  normalizeServiceIconKey,
  resolveServiceIcon,
  SERVICE_ICON_REGISTRY,
} from "./icon-registry";

describe("icon-registry", () => {
  it("contains all 18 backend-allowed icon keys with non-empty metadata", () => {
    expect(ALLOWED_ICON_KEYS).toHaveLength(18);
    expect(SERVICE_ICON_REGISTRY).toHaveLength(18);
    const seen = new Set<string>();
    for (const entry of SERVICE_ICON_REGISTRY) {
      expect(ALLOWED_ICON_KEYS).toContain(entry.key);
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.description.length).toBeGreaterThan(0);
      expect(entry.keywords.length).toBeGreaterThan(0);
      expect(entry.icon).toBeDefined();
      seen.add(entry.key);
    }
    expect(seen.size).toBe(18);
  });

  it("normalizes canonical and case-insensitive icon keys and legacy aliases", () => {
    expect(normalizeServiceIconKey("truck")).toBe("truck");
    expect(normalizeServiceIconKey("  Plane ")).toBe("plane");
    expect(normalizeServiceIconKey("box")).toBe("package");
    expect(normalizeServiceIconKey("unknown-random-icon")).toBeNull();
    expect(normalizeServiceIconKey("")).toBeNull();
    expect(normalizeServiceIconKey(null)).toBeNull();
  });

  it("resolves metadata and falls back to Package icon when unknown", () => {
    const truckMeta = getServiceIconMeta("truck");
    expect(truckMeta?.label).toBe("Road & Surface");
    expect(getServiceIconMeta("nonexistent")).toBeNull();
    expect(resolveServiceIcon("nonexistent")).toBe( getServiceIconMeta("package")?.icon );
  });
});
