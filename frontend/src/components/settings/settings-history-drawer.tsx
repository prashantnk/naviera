// frontend/src/components/settings/settings-history-drawer.tsx
"use client";

import { TenantsService, type TenantSettingsHistoryRead } from "@/api_client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { extractApiErrorMessage, formatIstDateTime } from "@/lib/utils";
import { getSupabaseClient } from "@/lib/supabase";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { History, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

/**
 * Busts the Next.js ISR cache (`tenant-<slug>` tag) after a settings save or
 * snapshot restore so marketing/public pages reflect the updated tenant config
 * immediately without waiting for the 1-hour revalidation window.
 */
export async function revalidateTenantSettingsCache(
  tenantSlug: string,
): Promise<void> {
  if (!tenantSlug) {
    return;
  }
  try {
    const {
      data: { session },
    } = await getSupabaseClient(tenantSlug).auth.getSession();
    const revalidateUrl = ["", "api", "revalidate"].join("/");
    await fetch(revalidateUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session?.access_token ?? ""}`,
      },
      body: JSON.stringify({ key: tenantSlug }),
    });
  } catch {
    // Non-blocking cache revalidation
  }
}

interface SettingsHistoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenantSlug: string;
  onRestored: () => Promise<void> | void;
}

export const SECTION_LABELS: Readonly<Record<string, string>> = {
  brand: "Branding & Logo",
  announcement_bar: "Announcement Bar",
  company: "Company Profile",
  contact: "Contact & Socials",
  support: "Help Center",
  landing_page: "Landing Page",
  about_page: "About Us",
  services_page: "Services",
  escalation_matrix: "Escalation Matrix",
  wallet_config: "Wallet & UPI",
  pricing_policy: "Pricing",
  pricing_config: "Rate Card (retired)",
  operations: "Operations",
  oAuthSignInEnabled: "Sign-in options",
  gstin: "GSTIN",
  user_roles: "User role change",
};

/**
 * Plain-English name of a changed settings section (unknown keys are shown as-is).
 *
 * @param section - Top-level settings key recorded in `changed_sections`.
 */
export function sectionLabel(section: string): string {
  return SECTION_LABELS[section] || section;
}

/**
 * Displays the last 20 settings snapshots for the tenant and lets an admin
 * restore any version with 1 click.
 */
export function SettingsHistoryDialog({
  open,
  onOpenChange,
  tenantSlug,
  onRestored,
}: SettingsHistoryDialogProps) {
  const [items, setItems] = useState<TenantSettingsHistoryRead[]>([]);
  const [loading, setLoading] = useState(false);
  const { pending: restoring, pendingKey: restoringId, run } = useSingleFlight();
  const [confirmEntry, setConfirmEntry] = useState<TenantSettingsHistoryRead | null>(null);

  useEffect(() => {
    if (!open || !tenantSlug) {
      setConfirmEntry(null);
      return;
    }
    setLoading(true);
    TenantsService.getSettingsHistory(tenantSlug)
      .then((res) => setItems(res))
      .catch((err) => {
        toast.error(extractApiErrorMessage(err, "Could not load settings history."));
      })
      .finally(() => setLoading(false));
  }, [open, tenantSlug]);

  const handleRestore = (entry: TenantSettingsHistoryRead) =>
    run(async () => {
      try {
        await TenantsService.restoreSettingsVersion(entry.id, tenantSlug);
        await revalidateTenantSettingsCache(tenantSlug);
        toast.success(`Restored settings snapshot #${entry.version}.`);
        setConfirmEntry(null);
        await onRestored();
        onOpenChange(false);
      } catch (err) {
        toast.error(extractApiErrorMessage(err, "Failed to restore settings snapshot."));
      }
    }, entry.id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="h-5 w-5 text-primary" />
            Settings Version History
          </DialogTitle>
          <DialogDescription>
            Each entry is one change (newest first). &ldquo;Restore before this&rdquo; puts back the
            settings as they were just before that change; your current settings are saved
            first, so a restore can be undone too. Pricing (markups, COD fee, services) and team
            roles are never changed by a restore.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 py-10 text-center text-sm text-slate-500">
            No history entries recorded yet. Your first save will create Version #1.
          </div>
        ) : (
          <div className="max-h-[380px] space-y-2.5 overflow-y-auto pr-1">
            {items.map((item) => (
              <div
                key={item.id}
                className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3.5 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-primary/10 px-2 py-0.5 font-mono text-xs font-bold text-primary">
                      v{item.version}
                    </span>
                    <span className="text-xs font-semibold text-slate-800">
                      {formatIstDateTime(item.created_at)}
                    </span>
                  </div>
                  {item.changed_by_email && (
                    <p className="text-[11px] text-slate-500">
                      Changed by <span className="font-medium text-slate-700">{item.changed_by_email}</span>
                    </p>
                  )}
                  {item.changed_sections && item.changed_sections.length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-0.5">
                      {item.changed_sections.map((sec) => (
                        <span
                          key={sec}
                          className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600"
                        >
                          {sectionLabel(sec)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {confirmEntry?.id === item.id ? (
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={restoring}
                      onClick={() => setConfirmEntry(null)}
                      className="h-8 px-2.5 text-xs bg-white"
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      disabled={restoring}
                      onClick={() => handleRestore(item)}
                      className="h-8 px-2.5 text-xs bg-primary text-primary-foreground hover:bg-primary/90"
                    >
                      {restoringId === item.id ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                      )}
                      Confirm Restore
                    </Button>
                  </div>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={restoring}
                    onClick={() => setConfirmEntry(item)}
                    className="shrink-0 bg-white"
                  >
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                    Restore before this
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
