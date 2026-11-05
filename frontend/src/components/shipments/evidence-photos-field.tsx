// frontend/src/components/shipments/evidence-photos-field.tsx
"use client";

/**
 * Optional photo evidence for a measurement (scale / tape photos), uploaded to the
 * tenant's folder in the private Supabase `documents` bucket. The field stores the
 * reference URLs that the measurements API keeps as evidence; viewing a photo opens a
 * short-lived signed URL.
 */
import { Camera, Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { documentReferenceUrl, openDocument, uploadTenantDocument } from "@/lib/document-storage";
import { extractApiErrorMessage } from "@/lib/utils";

/** Backend limit on evidence URLs per measurement. */
export const MAX_EVIDENCE_PHOTOS = 3;
/** Same 5 MB cap as the other document uploads. */
const MAX_PHOTO_BYTES = 5242880;
const PHOTO_KEY_LABEL = "measurement";

/** Props of {@link EvidencePhotosField}. */
export interface EvidencePhotosFieldProps {
  tenantSlug: string;
  value: string[];
  onChange: (urls: string[]) => void;
  testIdPrefix: string;
  disabled?: boolean;
}

/**
 * Uploads one photo and returns its reference URL.
 *
 * @param tenantSlug - Tenant folder in the bucket.
 * @param file - Image chosen by the user.
 * @returns Reference URL of the stored (private) object.
 */
async function _uploadPhoto(tenantSlug: string, file: File): Promise<string> {
  return documentReferenceUrl(await uploadTenantDocument(tenantSlug, file, PHOTO_KEY_LABEL));
}

/** Up to three optional evidence photos with remove buttons. */
export function EvidencePhotosField({
  tenantSlug,
  value,
  onChange,
  testIdPrefix,
  disabled = false,
}: EvidencePhotosFieldProps) {
  const { pending: uploading, run: runUpload } = useSingleFlight();
  const { pendingKey: openingUrl, run: runView } = useSingleFlight();
  const isFull = value.length >= MAX_EVIDENCE_PHOTOS;

  const handleView = (url: string) =>
    runView(async () => {
      try {
        if (!(await openDocument(tenantSlug, url))) toast.error("Could not open this photo.");
      } catch (err: unknown) {
        toast.error(extractApiErrorMessage(err, "Could not open this photo."));
      }
    }, url);

  const handleFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      toast.error("Photo must be under 5 MB.");
      return;
    }
    await runUpload(async () => {
      try {
        const url = await _uploadPhoto(tenantSlug, file);
        onChange([...value, url]);
        toast.success("Photo added.");
      } catch (err: unknown) {
        toast.error(extractApiErrorMessage(err, "Photo upload failed."));
      }
    });
  };

  return (
    <div data-testid={testIdPrefix} className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        {value.map((url, index) => (
          <span
            key={url}
            data-testid={`${testIdPrefix}.photo-${index}`}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-[11px] font-medium"
          >
            <button
              type="button"
              data-testid={`${testIdPrefix}.view-${index}`}
              onClick={() => void handleView(url)}
              disabled={openingUrl !== null}
              aria-busy={openingUrl === url}
              className="inline-flex items-center text-primary hover:underline"
            >
              {openingUrl === url && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
              Photo {index + 1}
            </button>
            <button
              type="button"
              disabled={disabled}
              aria-label={`Remove photo ${index + 1}`}
              onClick={() => onChange(value.filter((item) => item !== url))}
              className="text-muted-foreground hover:text-destructive"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          asChild
          disabled={disabled || uploading || isFull}
          className="h-9"
        >
          <label
            data-testid={`${testIdPrefix}.add`}
            className={isFull || disabled ? "pointer-events-none opacity-50" : "cursor-pointer"}
          >
            {uploading ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Camera className="mr-1.5 h-4 w-4" />}
            Add photo
            <input
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              disabled={disabled || uploading || isFull}
              onChange={handleFile}
            />
          </label>
        </Button>
      </div>
      <p className="text-[11px] text-muted-foreground">Optional, up to {MAX_EVIDENCE_PHOTOS} photos.</p>
    </div>
  );
}
