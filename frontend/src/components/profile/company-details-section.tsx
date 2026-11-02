// frontend/src/components/profile/company-details-section.tsx
"use client";

import { UsersService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import {
  BILLING_ADDRESS_MAX,
  COMPANY_NAME_MAX,
  EMPTY_COMPANY_DETAILS,
  GSTIN_LENGTH,
  companyDetailsSchema,
  toCompanyDetailsPayload,
  type CompanyDetailsFormValues,
  type CompanyDetailsParsed,
} from "@/components/profile/company-details-form";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { extractApiErrorMessage } from "@/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import { Building2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

/** Window event AuthGuard listens to for re-fetching `/users/me` (same as ProfileDialog). */
const PROFILE_UPDATED_EVENT = "user-profile-updated";

/**
 * "Company details" in My profile (prelaunch audit C-01; Delhivery One `profile`).
 * They are printed as "Bill To" on the seller's GST invoices and credit / debit notes.
 * A seller enters them once; afterwards they are view-only and changes go through a
 * support ticket. Staff accounts are not billed, so the section is hidden for them.
 */
export function CompanyDetailsSection() {
  const { user, isAdmin } = useUser();
  const { routeTo } = useTenant();
  const form = useForm<CompanyDetailsFormValues, unknown, CompanyDetailsParsed>({
    resolver: zodResolver(companyDetailsSchema),
    defaultValues: EMPTY_COMPANY_DETAILS,
  });

  if (!user || isAdmin) {
    return null;
  }

  const onSubmit = async (values: CompanyDetailsParsed) => {
    try {
      await UsersService.updateMyProfile({
        company_details: toCompanyDetailsPayload(values),
      });
      window.dispatchEvent(new CustomEvent(PROFILE_UPDATED_EVENT));
      toast.success("Company details saved");
    } catch (error: unknown) {
      toast.error(extractApiErrorMessage(error, "Could not save your company details"));
    }
  };

  if (user.company_details_locked) {
    return (
      <div
        className="space-y-2 rounded-lg border border-border bg-muted/40 p-3"
        data-testid="profile.company-details.view"
      >
        <p className="flex items-center gap-1.5 text-xs font-semibold">
          <Building2 className="h-3.5 w-3.5 text-primary" />
          Company details (printed on your GST invoices)
        </p>
        <dl className="space-y-1 text-xs">
          <div>
            <dt className="text-muted-foreground">Company name</dt>
            <dd className="font-medium">{user.company_name || "-"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Billing address</dt>
            <dd className="font-medium">{user.billing_address || "-"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">GSTIN</dt>
            <dd className="font-mono font-medium" data-testid="profile.company-details.gstin">
              {user.gstin || "Unregistered"}
            </dd>
          </div>
        </dl>
        <p className="text-[11px] text-muted-foreground">
          To change these details,{" "}
          <Link href={routeTo("/support")} className="font-medium text-primary hover:underline">
            raise a support ticket
          </Link>
          .
        </p>
      </div>
    );
  }

  const { errors, isSubmitting } = form.formState;
  return (
    <form
      onSubmit={form.handleSubmit(onSubmit)}
      className="space-y-3 rounded-lg border border-border p-3"
      data-testid="profile.company-details.form"
    >
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold">
          <Building2 className="h-3.5 w-3.5 text-primary" />
          Company details
        </p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Printed as &quot;Bill To&quot; on your GST invoices so you can claim input tax
          credit. You can enter them once; later changes need a support ticket.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="company-legal-name" className="text-xs font-semibold">
          Registered company / business name
        </Label>
        <Input
          id="company-legal-name"
          maxLength={COMPANY_NAME_MAX}
          data-testid="profile.company-details.legal-name"
          {...form.register("legalName")}
        />
        {errors.legalName && (
          <p className="text-[11px] text-destructive">{errors.legalName.message}</p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="company-billing-address" className="text-xs font-semibold">
          Billing address
        </Label>
        <Textarea
          id="company-billing-address"
          rows={2}
          maxLength={BILLING_ADDRESS_MAX}
          data-testid="profile.company-details.billing-address"
          {...form.register("billingAddress")}
        />
        {errors.billingAddress && (
          <p className="text-[11px] text-destructive">{errors.billingAddress.message}</p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="company-gstin" className="text-xs font-semibold">
          GSTIN (optional)
        </Label>
        <Input
          id="company-gstin"
          maxLength={GSTIN_LENGTH}
          className="font-mono uppercase"
          placeholder="Leave blank if not GST-registered"
          data-testid="profile.company-details.gstin-input"
          {...form.register("gstin")}
        />
        {errors.gstin && <p className="text-[11px] text-destructive">{errors.gstin.message}</p>}
      </div>
      <div className="flex justify-end">
        <Button
          type="submit"
          size="sm"
          disabled={isSubmitting}
          data-testid="profile.company-details.save"
        >
          {isSubmitting && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
          Save company details
        </Button>
      </div>
    </form>
  );
}
