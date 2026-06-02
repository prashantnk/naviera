// frontend/src/lib/api/postal.ts

export interface PostOfficeDetails {
  Name: string;
  Description: string | null;
  BranchType: string;
  DeliveryStatus: string;
  Circle: string;
  District: string;
  Division: string;
  Region: string;
  State: string;
  Country: string;
  Pincode: string;
}

export interface PostalPincodeResponse {
  Message: string;
  Status: "Success" | "Error";
  PostOffice: PostOfficeDetails[] | null;
}

/**
 * Fetches geographical data for a given Indian pincode from the public postal API.
 */
export async function fetchPostalDataByPincode(
  pincode: string,
  signal?: AbortSignal
): Promise<PostalPincodeResponse[]> {
  const cleanPincode = pincode.replace(/[\s-]/g, "");
  const res = await fetch(`https://api.postalpincode.in/pincode/${cleanPincode}`, { signal });
  if (!res.ok) {
    throw new Error(`Failed to lookup pincode: ${res.statusText}`);
  }
  return res.json();
}
