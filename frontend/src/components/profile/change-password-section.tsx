// frontend/src/components/profile/change-password-section.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { getSupabaseClient } from "@/lib/supabase";
import { KeyRound, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

/** Same minimum as sign-up / reset on the login page (`login-form.tsx`). */
export const MIN_PASSWORD_LENGTH = 8;

/**
 * Validates a new password pair before it is sent to Supabase.
 *
 * @returns The error to show, or null when the pair is acceptable.
 */
export function newPasswordError(password: string, confirmation: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `New password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (password !== confirmation) {
    return "The two passwords do not match.";
  }
  return null;
}

/**
 * "Change password" in My profile (Delhivery One profile settings). A signed-in user
 * sets a new password on their Supabase account; the current session stays valid.
 * Collapsed by default so the profile form stays short.
 */
export function ChangePasswordSection() {
  const { tenantSlug } = useTenant();
  const [expanded, setExpanded] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const { pending: saving, run } = useSingleFlight();
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setPassword("");
    setConfirmation("");
    setError(null);
  };

  const handleSave = async () => {
    const validationError = newPasswordError(password, confirmation);
    setError(validationError);
    if (validationError) return;
    await run(async () => {
      try {
        const { error: updateError } = await getSupabaseClient(tenantSlug).auth.updateUser({
          password,
        });
        if (updateError) {
          setError(updateError.message);
          toast.error(updateError.message);
          return;
        }
        toast.success("Password changed. Use the new password next time you sign in.");
        reset();
        setExpanded(false);
      } catch {
        const message = "Could not change your password. Please try again.";
        setError(message);
        toast.error(message);
      }
    });
  };

  if (!expanded) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-border p-3">
        <p className="flex items-center gap-1.5 text-xs font-semibold">
          <KeyRound className="h-3.5 w-3.5 text-primary" />
          Password
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setExpanded(true)}
          data-testid="profile.password.open"
        >
          Change password
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-border p-3" data-testid="profile.password.form">
      <p className="flex items-center gap-1.5 text-xs font-semibold">
        <KeyRound className="h-3.5 w-3.5 text-primary" />
        Change password
      </p>
      <div className="space-y-1.5">
        <Label htmlFor="profile-new-password" className="text-xs font-semibold">
          New password
        </Label>
        <Input
          id="profile-new-password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="profile-confirm-password" className="text-xs font-semibold">
          Confirm new password
        </Label>
        <Input
          id="profile-confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirmation}
          onChange={(e) => setConfirmation(e.target.value)}
        />
      </div>
      {error && (
        <p className="text-[11px] text-destructive" role="alert">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            reset();
            setExpanded(false);
          }}
          disabled={saving}
        >
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={saving}
          data-testid="profile.password.save"
        >
          {saving && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
          Update password
        </Button>
      </div>
    </div>
  );
}
