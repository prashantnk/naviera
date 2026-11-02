// frontend/src/components/shipments/evidence-photos-field.tsx
"use client";

/**
 * Optional photo evidence for a measurement (scale / tape photos), uploaded to the
 * tenant's Supabase `documents` bucket the same way shipment documents are uploaded.
 * The field stores the public URLs that the measurements API keeps as evidence.
 */
import { Camera, Loader2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase";
import { extractApiErrorMessage } from "@/lib/utils";

/** Backend limit on evidence URLs per measurement. */
export const MAX_EVIDENCE_PHOTOS = 3;
/** Same 5 MB cap as the other document uploads. */
const MAX_PHOTO_BYTES = 5242880;
const STORAGE_BUCKET = "documents";
const UNSAFE_FILENAME_CHARS = /[^a-zA-Z0-9.-]/g;

/** Props of {@link EvidencePhotosField}. */
export interface EvidencePhotosFieldProps {
  tenantSlug: string;
  value: string[];
  onChange: (urls: string[]) => void;
  testIdPrefix: string;
  disabled?: boolean;
}

/**
 * Uploads one photo and returns its public URL.
 *
 * @param tenantSlug - Tenant folder in the bucket.
 * @param file - Image chosen by the user.
 * @returns Public URL of the stored object.
 */
async function _uploadPhoto(tenantSlug: string, file: File): Promise<string> {
  const supabase = getSupabaseClient(tenantSlug);
  const safeName = file.name.replace(UNSAFE_FILENAME_CHARS, "_");
  const storagePath = [tenantSlug, `measurement_${Date.now()}_${safeName}`].join("/");
  const { error } = await supabase.storage.from(STORAGE_BUCKET).upload(storagePath, file, { upsert: true });
  if (error) throw error;
  return supabase.storage.from(STORAGE_BUCKET).getPublicUrl(storagePath).data.publicUrl;
}

/** Up to three optional evidence photos with remove buttons. */
export function EvidencePhotosField({
  tenantSlug,
  value,
  onChange,
  testIdPrefix,
  disabled = false,
}: EvidencePhotosFieldProps) {
  const [uploading, setUploading] = useState(false);
  const isFull = value.length >= MAX_EVIDENCE_PHOTOS;

  const handleFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      toast.error("Photo must be under 5 MB.");
      return;
    }
    setUploading(true);
    try {
      const url = await _uploadPhoto(tenantSlug, file);
      onChange([...value, url]);
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Photo upload failed."));
    } finally {
      setUploading(false);
    }
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
            <a href={url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
              Photo {index + 1}
            </a>
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
