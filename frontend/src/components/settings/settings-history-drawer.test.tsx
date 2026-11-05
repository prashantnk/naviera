// frontend/src/components/settings/settings-history-drawer.test.tsx
import { TenantsService, type TenantSettingsHistoryRead } from "@/api_client";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsHistoryDialog } from "./settings-history-drawer";

vi.mock("@/api_client", () => ({
  TenantsService: {
    getSettingsHistory: vi.fn(),
    restoreSettingsVersion: vi.fn(),
  },
}));

vi.mock("@/lib/supabase", () => ({
  getSupabaseClient: () => ({
    auth: { getSession: async () => ({ data: { session: null } }) },
  }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ENTRY = {
  id: "hist-7",
  version: 7,
  created_at: "2026-11-04T10:00:00Z",
  changed_sections: ["brand"],
} as TenantSettingsHistoryRead;

describe("SettingsHistoryDialog restore", () => {
  beforeEach(() => {
    vi.mocked(TenantsService.getSettingsHistory).mockReset().mockResolvedValue([ENTRY]);
    vi.mocked(TenantsService.restoreSettingsVersion).mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null)));
  });

  it("restores once on a fast double click, spinning until the API answers", async () => {
    let resolveRestore!: () => void;
    vi.mocked(TenantsService.restoreSettingsVersion).mockReturnValue(
      new Promise<void>((resolve) => {
        resolveRestore = resolve;
      }) as unknown as ReturnType<typeof TenantsService.restoreSettingsVersion>,
    );
    const onRestored = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <SettingsHistoryDialog
        open
        onOpenChange={onOpenChange}
        tenantSlug="logismart-test"
        onRestored={onRestored}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /Restore before this/ }));
    const confirm = screen.getByRole("button", { name: /Confirm Restore/ });
    act(() => {
      fireEvent.click(confirm);
      fireEvent.click(confirm);
    });

    expect(TenantsService.restoreSettingsVersion).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    expect(confirm.querySelector(".animate-spin")).not.toBeNull();

    await act(async () => {
      resolveRestore();
    });
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Restored settings snapshot #7."));
    expect(onRestored).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("toasts the API error and re-enables the button", async () => {
    vi.mocked(TenantsService.restoreSettingsVersion).mockRejectedValue(new Error("Snapshot is gone"));
    render(
      <SettingsHistoryDialog open onOpenChange={vi.fn()} tenantSlug="logismart-test" onRestored={vi.fn()} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /Restore before this/ }));
    const confirm = screen.getByRole("button", { name: /Confirm Restore/ });
    fireEvent.click(confirm);

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Snapshot is gone"));
    expect(confirm).toBeEnabled();
  });
});
