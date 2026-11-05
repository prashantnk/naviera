// frontend/src/components/blocks/profile-dialog.tsx
"use client";

import { UsersService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { CompanyDetailsSection } from "@/components/profile/company-details-section";
import { ChangePasswordSection } from "@/components/profile/change-password-section";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { extractApiErrorMessage } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

/** Window event AuthGuard listens to for re-fetching `/users/me`. */
const PROFILE_UPDATED_EVENT = "user-profile-updated";
const MAX_NAME_LENGTH = 120;
/** Indian mobile number: 10 digits starting 6-9, optionally written with +91 / 0. */
const INDIAN_MOBILE_PATTERN = /^(?:\+91|91|0)?[6-9]\d{9}$/;

/**
 * Normalises a typed mobile number (spaces / dashes removed).
 *
 * @returns The cleaned number, "" when blank, or null when it is not a valid Indian mobile.
 */
export function normalizeMobile(raw: string): string | null {
  const cleaned = raw.replace(/[\s-]/g, "");
  if (!cleaned) return "";
  return INDIAN_MOBILE_PATTERN.test(cleaned) ? cleaned : null;
}

interface ProfileDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * "My profile" dialog: any signed-in user edits their own display name and
 * phone (`PATCH /api/v1/users/me`). Role, scope and status stay with Owner/Admin
 * on the Users page.
 */
export function ProfileDialog({ open, onOpenChange }: ProfileDialogProps) {
  const { user } = useUser();
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const { pending: saving, run } = useSingleFlight();

  useEffect(() => {
    if (open) {
      setFullName(user?.full_name || "");
      setPhone(user?.phone || "");
    }
  }, [open, user?.full_name, user?.phone]);

  const handleSave = async () => {
    if (!fullName.trim()) {
      toast.error("Please enter your name");
      return;
    }
    const mobile = normalizeMobile(phone);
    if (mobile === null) {
      toast.error("Enter a valid 10-digit mobile number, or leave it blank");
      return;
    }
    await run(async () => {
      try {
        await UsersService.updateMyProfile({
          full_name: fullName.trim(),
          phone: mobile || null,
        });
        window.dispatchEvent(new CustomEvent(PROFILE_UPDATED_EVENT));
        toast.success("Profile updated");
        onOpenChange(false);
      } catch (error: unknown) {
        toast.error(extractApiErrorMessage(error, "Could not update your profile"));
      }
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col overflow-hidden sm:max-w-md">
        <DialogHeader className="shrink-0">
          <DialogTitle>My profile</DialogTitle>
          <DialogDescription>
            Your name is shown in the app, on tickets and to the Logismart team.
          </DialogDescription>
        </DialogHeader>

        <div
          data-testid="profile.dialog.body"
          className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1"
        >
          <div className="space-y-1.5">
            <Label htmlFor="profile-full-name" className="text-xs font-semibold">
              Full name
            </Label>
            <Input
              id="profile-full-name"
              value={fullName}
              maxLength={MAX_NAME_LENGTH}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Enter your full name"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="profile-phone" className="text-xs font-semibold">
              Mobile number
            </Label>
            <Input
              id="profile-phone"
              value={phone}
              inputMode="tel"
              onChange={(e) => setPhone(e.target.value)}
              placeholder="10-digit mobile number"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="profile-email" className="text-xs font-semibold">
              Email
            </Label>
            <Input
              id="profile-email"
              value={user?.email || ""}
              readOnly
              className="bg-muted text-muted-foreground cursor-not-allowed"
            />
          </div>
          <CompanyDetailsSection />
          <ChangePasswordSection />
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t border-border pt-3">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            Save
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
