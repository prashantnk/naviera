// frontend/src/lib/document-storage.test.ts
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const upload = vi.fn();
const createSignedUrl = vi.fn();
const from = vi.fn(() => ({ upload, createSignedUrl }));

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({ storage: { from } }),
}));

import {
  DOCUMENTS_BUCKET,
  SIGNED_URL_TTL_SECONDS,
  buildDocumentObjectKey,
  documentObjectKey,
  documentReferenceUrl,
  openDocument,
  signDocumentUrl,
  uploadTenantDocument,
  useSignedDocumentUrl,
} from "./document-storage";

const SUPABASE_URL = "https://proj.supabase.co";
const SIGNED = "https://proj.supabase.co/storage/v1/object/sign/documents/logismart-test/a.png?token=t";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", `${SUPABASE_URL}/`);
  createSignedUrl.mockResolvedValue({ data: { signedUrl: SIGNED }, error: null });
  upload.mockResolvedValue({ data: {}, error: null });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("buildDocumentObjectKey", () => {
  it("prefixes the tenant folder and sanitises the file name", () => {
    expect(buildDocumentObjectKey("logismart-test", "scale photo (1).jpg", "measurement", 42)).toBe(
      "logismart-test/measurement_42_scale_photo__1_.jpg",
    );
  });
});

describe("documentObjectKey", () => {
  it.each([
    ["logismart/abc.pdf", "logismart/abc.pdf"],
    ["/documents/logismart/abc.pdf", "logismart/abc.pdf"],
    [`${SUPABASE_URL}/storage/v1/object/public/documents/logismart/m_1_a.png`, "logismart/m_1_a.png"],
    ["https://naviera.vercel.app/supabase-proxy/storage/v1/object/public/documents/logismart/x.png", "logismart/x.png"],
    [`${SUPABASE_URL}/storage/v1/object/sign/documents/logismart/x.png?token=abc`, "logismart/x.png"],
    [`${SUPABASE_URL}/storage/v1/object/authenticated/documents/logismart/a%20b.png`, "logismart/a b.png"],
  ])("derives the key from %s", (reference, expected) => {
    expect(documentObjectKey(reference)).toBe(expected);
  });

  it.each(["", "   ", "https://cdn.delhivery.com/sorter/1.jpg", `${SUPABASE_URL}/storage/v1/object/public/other/x.png`])(
    "returns null for %j",
    (reference) => {
      expect(documentObjectKey(reference)).toBeNull();
    },
  );

  it("returns null for a malformed percent-encoding", () => {
    expect(documentObjectKey(`${SUPABASE_URL}/storage/v1/object/public/documents/bad%E0%A4`)).toBeNull();
  });
});

describe("documentReferenceUrl", () => {
  it("names the private object and round-trips through documentObjectKey", () => {
    const url = documentReferenceUrl("logismart-test/ndr_1_a b.pdf");
    expect(url).toBe(`${SUPABASE_URL}/storage/v1/object/authenticated/documents/logismart-test/ndr_1_a%20b.pdf`);
    expect(documentObjectKey(url)).toBe("logismart-test/ndr_1_a b.pdf");
  });
});

describe("uploadTenantDocument", () => {
  it("uploads into the tenant folder without overwriting", async () => {
    const file = new File(["x"], "pod.pdf");
    const key = await uploadTenantDocument("logismart-test", file, "ndr");
    expect(key).toMatch(/^logismart-test\/ndr_\d+_pod\.pdf$/);
    expect(from).toHaveBeenCalledWith(DOCUMENTS_BUCKET);
    expect(upload).toHaveBeenCalledWith(key, file);
  });

  it("throws the storage error (e.g. the tenant policy rejected the path)", async () => {
    upload.mockResolvedValue({ data: null, error: new Error("new row violates row-level security policy") });
    await expect(uploadTenantDocument("logismart-test", new File(["x"], "a.pdf"), "doc")).rejects.toThrow(
      "row-level security",
    );
  });
});

describe("signDocumentUrl", () => {
  it("signs legacy public URLs instead of opening them", async () => {
    const legacy = `${SUPABASE_URL}/storage/v1/object/public/documents/logismart-test/a.png`;
    await expect(signDocumentUrl("logismart-test", legacy)).resolves.toBe(SIGNED);
    expect(createSignedUrl).toHaveBeenCalledWith("logismart-test/a.png", SIGNED_URL_TTL_SECONDS);
  });

  it("returns URLs outside the bucket unchanged", async () => {
    await expect(signDocumentUrl("logismart-test", " https://cdn.delhivery.com/1.jpg ")).resolves.toBe(
      "https://cdn.delhivery.com/1.jpg",
    );
    expect(createSignedUrl).not.toHaveBeenCalled();
  });

  it("returns null when signing is refused or the reference is empty", async () => {
    createSignedUrl.mockResolvedValue({ data: null, error: new Error("Object not found") });
    await expect(signDocumentUrl("logismart-test", "logismart/other-tenant.pdf")).resolves.toBeNull();
    await expect(signDocumentUrl("logismart-test", "")).resolves.toBeNull();
  });
});

describe("openDocument", () => {
  it("opens the signed URL in a new tab", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    await expect(openDocument("logismart-test", "logismart-test/a.png")).resolves.toBe(true);
    expect(open).toHaveBeenCalledWith(SIGNED, "_blank", "noopener,noreferrer");
  });

  it("reports failure without opening anything", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    createSignedUrl.mockResolvedValue({ data: null, error: new Error("denied") });
    await expect(openDocument("logismart-test", "logismart/a.png")).resolves.toBe(false);
    expect(open).not.toHaveBeenCalled();
  });
});

describe("useSignedDocumentUrl", () => {
  it("resolves the stored reference to a signed URL", async () => {
    const { result } = renderHook(() => useSignedDocumentUrl("logismart-test", "logismart-test/a.png"));
    await waitFor(() => expect(result.current).toBe(SIGNED));
  });

  it("stays null without a reference and when signing throws", async () => {
    const empty = renderHook(() => useSignedDocumentUrl("logismart-test", null));
    expect(empty.result.current).toBeNull();
    createSignedUrl.mockRejectedValue(new Error("network"));
    const failing = renderHook(() => useSignedDocumentUrl("logismart-test", "logismart-test/b.png"));
    await waitFor(() => expect(createSignedUrl).toHaveBeenCalled());
    expect(failing.result.current).toBeNull();
  });
});
