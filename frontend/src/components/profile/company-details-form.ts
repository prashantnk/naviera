// frontend/src/components/profile/company-details-form.ts
import type { SellerCompanyDetailsSubmit } from "@/api_client";
import * as z from "zod";

/** Field limits mirror `SellerCompanyDetailsSubmit` in `backend/app/schemas/v1/tenants.py`. */
export const COMPANY_NAME_MIN = 2;
export const COMPANY_NAME_MAX = 160;
export const BILLING_ADDRESS_MIN = 10;
export const BILLING_ADDRESS_MAX = 300;
export const GSTIN_LENGTH = 15;

/**
 * GSTIN shape only (2-digit state, PAN, entity, "Z", check character). The backend
 * also verifies the checksum and that it is not the tenant's own GSTIN.
 */
const GSTIN_FORMAT = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export const companyDetailsSchema = z.object({
  legalName: z
    .string()
    .trim()
    .min(COMPANY_NAME_MIN, "Enter your registered company or business name")
    .max(COMPANY_NAME_MAX),
  billingAddress: z
    .string()
    .trim()
    .min(BILLING_ADDRESS_MIN, "Enter the full billing address with city and PIN code")
    .max(BILLING_ADDRESS_MAX),
  gstin: z
    .string()
    .trim()
    .transform((value) => value.toUpperCase())
    .refine(
      (value) => value === "" || GSTIN_FORMAT.test(value),
      "Enter a valid 15-character GSTIN, or leave it blank if you are not GST-registered"
    ),
});

export type CompanyDetailsFormValues = z.input<typeof companyDetailsSchema>;
export type CompanyDetailsParsed = z.output<typeof companyDetailsSchema>;

export const EMPTY_COMPANY_DETAILS: CompanyDetailsFormValues = {
  legalName: "",
  billingAddress: "",
  gstin: "",
};

/** Maps the parsed form to the `PATCH /users/me` `company_details` body (blank GSTIN = unregistered). */
export function toCompanyDetailsPayload(
  values: CompanyDetailsParsed
): SellerCompanyDetailsSubmit {
  return {
    legal_name: values.legalName,
    billing_address: values.billingAddress,
    gstin: values.gstin || null,
  };
}
