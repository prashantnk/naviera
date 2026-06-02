// frontend/src/hooks/use-pincode-locator.ts
import { useState, useEffect } from "react";
import { UseFormSetValue, FieldValues, Path, PathValue } from "react-hook-form";
import { fetchPostalDataByPincode } from "@/lib/api/postal";

export interface UsePincodeLocatorProps<T extends FieldValues> {
  pincodeValue: string | undefined;
  setValue: UseFormSetValue<T>;
  cityField: Path<T>;
  stateField: Path<T>;
}

/**
 * A reusable custom React hook that automatically debounces pincode changes,
 * calls the public Postal PIN Code API, and sets the resolved city & state values in the form.
 */
export function usePincodeLocator<T extends FieldValues>({
  pincodeValue,
  setValue,
  cityField,
  stateField,
}: UsePincodeLocatorProps<T>) {
  const [isLocating, setIsLocating] = useState(false);
  const [geoVerified, setGeoVerified] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);

  useEffect(() => {
    const cleanPincode = (pincodeValue || "").replace(/[\s-]/g, "");
    if (cleanPincode.length !== 6 || !/^[1-9][0-9]{5}$/.test(cleanPincode)) {
      setGeoVerified(false);
      setGeoError(null);
      return;
    }

    const controller = new AbortController();
    setIsLocating(true);
    setGeoError(null);

    const timer = setTimeout(async () => {
      try {
        const data = await fetchPostalDataByPincode(cleanPincode, controller.signal);
        if (data?.[0]?.Status === "Success" && data[0].PostOffice && data[0].PostOffice.length > 0) {
          const postOffice = data[0].PostOffice[0];
          // Force strict casting internally using react-hook-form types to satisfy zero-any directives
          setValue(cityField, postOffice.District as PathValue<T, Path<T>>, { shouldValidate: true });
          setValue(stateField, postOffice.State as PathValue<T, Path<T>>, { shouldValidate: true });
          setGeoVerified(true);
          setGeoError(null);
        } else {
          setGeoVerified(false);
          setGeoError("Could not verify pincode. Please enter City and State manually.");
        }
      } catch (err: unknown) {
        const error = err instanceof Error ? err : new Error(String(err));
        if (error.name !== "AbortError") {
          console.error("Pincode lookup failed", error);
          setGeoVerified(false);
          setGeoError("Could not verify pincode. Please enter City and State manually.");
        }
      } finally {
        setIsLocating(false);
      }
    }, 300);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [pincodeValue, setValue, cityField, stateField]);

  return { isLocating, geoVerified, geoError, setGeoVerified };
}
