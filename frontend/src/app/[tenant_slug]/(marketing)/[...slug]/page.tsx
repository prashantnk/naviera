// frontend/src/app/[tenant_slug]/(marketing)/[...slug]/page.tsx
import { notFound } from "next/navigation";

/**
 * Catch-all for unknown public paths (`/<tenant>/anything`). Throwing `notFound()`
 * renders the sibling `not-found.tsx` inside the marketing layout (header/footer)
 * AND makes Next.js answer HTTP 404 instead of a "soft 404" 200, so search engines
 * never index broken links.
 *
 * Spring Boot analogy: a fallback `@RequestMapping("/**")` that throws
 * `ResponseStatusException(HttpStatus.NOT_FOUND)`.
 */
export default function CatchAll404Page(): never {
  notFound();
}
