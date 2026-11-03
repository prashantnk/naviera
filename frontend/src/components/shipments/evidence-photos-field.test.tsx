// frontend/src/components/shipments/evidence-photos-field.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const upload = vi.fn();
const createSignedUrl = vi.fn();

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({ storage: { from: () => ({ upload, createSignedUrl }) } }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

import { toast } from "sonner";

import { EvidencePhotosField } from "./evidence-photos-field";

const SUPABASE_URL = "https://proj.supabase.co";
const SIGNED = `${SUPABASE_URL}/storage/v1/object/sign/documents/logismart-test/p.jpg?token=t`;

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", SUPABASE_URL);
  upload.mockResolvedValue({ data: {}, error: null });
  createSignedUrl.mockResolvedValue({ data: { signedUrl: SIGNED }, error: null });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("EvidencePhotosField", () => {
  it("stores a private reference URL inside the tenant folder, not a public URL", async () => {
    const onChange = vi.fn();
    const { container } = render(
      <EvidencePhotosField tenantSlug="logismart-test" value={[]} onChange={onChange} testIdPrefix="ev" />,
    );
    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["img"], "scale.jpg", { type: "image/jpeg" })] } });

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    const [[urls]] = onChange.mock.calls;
    expect(urls[0]).toMatch(
      new RegExp(`^${SUPABASE_URL}/storage/v1/object/authenticated/documents/logismart-test/measurement_\\d+_scale\\.jpg$`),
    );
    expect(upload.mock.calls[0][0]).toMatch(/^logismart-test\//);
    expect(upload.mock.calls[0]).toHaveLength(2);
  });

  it("opens a stored photo (including a legacy public URL) through a signed URL", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const legacy = `${SUPABASE_URL}/storage/v1/object/public/documents/logismart-test/p.jpg`;
    render(<EvidencePhotosField tenantSlug="logismart-test" value={[legacy]} onChange={vi.fn()} testIdPrefix="ev" />);

    fireEvent.click(screen.getByTestId("ev.view-0"));

    await waitFor(() => expect(open).toHaveBeenCalledWith(SIGNED, "_blank", "noopener,noreferrer"));
    expect(createSignedUrl).toHaveBeenCalledWith("logismart-test/p.jpg", 60);
  });

  it("tells the user when the photo cannot be opened", async () => {
    createSignedUrl.mockResolvedValue({ data: null, error: new Error("denied") });
    render(
      <EvidencePhotosField tenantSlug="logismart-test" value={["logismart/x.jpg"]} onChange={vi.fn()} testIdPrefix="ev" />,
    );

    fireEvent.click(screen.getByTestId("ev.view-0"));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Could not open this photo."));
  });
});
