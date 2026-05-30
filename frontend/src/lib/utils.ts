import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Helper to format Pickup Time Slot to 12HR format
export const formatTimeSlot = (slot: string) => {
  const mapping: Record<string, string> = {
    "06:00 - 10:00": "06:00 AM - 10:00 AM",
    "10:00 - 14:00": "10:00 AM - 02:00 PM",
    "14:00 - 18:00": "02:00 PM - 06:00 PM",
    "18:00 - 22:00": "06:00 PM - 10:00 PM",
  };
  return mapping[slot] || slot;
};
