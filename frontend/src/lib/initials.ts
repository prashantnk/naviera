// frontend/src/lib/initials.ts
/**
 * Avatar initials for a user, shared by the app header and the Users page.
 *
 * Only letters and digits count, so display names that carry a tag such as
 * "Owner (Test)" give "OT" instead of "O(".
 */

/** Initials shown when neither a name nor an email is available. */
const FALLBACK_INITIALS = "U";
/** Maximum number of characters in an avatar. */
const MAX_INITIALS = 2;
/** Characters that never start or form part of initials. */
const NON_ALPHANUMERIC = /[^\p{L}\p{N}]+/gu;

/**
 * Splits text into alphanumeric words ("Owner (Test)" -> ["Owner", "Test"]).
 *
 * @param text - Display name or email local part.
 * @returns Non-empty words.
 */
function _words(text: string): string[] {
  return text.split(NON_ALPHANUMERIC).filter((word) => word.length > 0);
}

/**
 * Builds up to two uppercase initials from a name, falling back to the email.
 *
 * @param fullName - The user's display name, if any.
 * @param email - The user's email, if any (only the part before "@" is used).
 * @returns Initials such as "OT", or "U" when nothing usable is known.
 */
export function getInitials(
  fullName?: string | null,
  email?: string | null
): string {
  const nameWords = _words(fullName ?? "");
  if (nameWords.length >= MAX_INITIALS) {
    return nameWords
      .slice(0, MAX_INITIALS)
      .map((word) => word.charAt(0))
      .join("")
      .toUpperCase();
  }
  if (nameWords.length === 1) {
    return nameWords[0].slice(0, MAX_INITIALS).toUpperCase();
  }
  const localPart = _words((email ?? "").split("@")[0]).join("");
  return localPart ? localPart.slice(0, MAX_INITIALS).toUpperCase() : FALLBACK_INITIALS;
}
