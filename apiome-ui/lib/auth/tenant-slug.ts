/**
 * Tenant slug derivation and validation, shared by every UI flow that creates a
 * tenant: OAuth self-signup (`oauth-signup-actions.ts`, OLO-2.x) and the
 * first-tenant onboarding wizard (`first-tenant-actions.ts`, OLO-4.1).
 *
 * Pure and dependency-free so it is importable from both server actions and
 * client components (the wizard previews the slug the server will use).
 */

/** Allowed shape of a stored tenant slug: lowercase letters, digits, dashes. */
const SLUG_REGEX = /^[a-z0-9-]+$/;

/**
 * Derive a URL-safe slug from a human-readable organization name.
 *
 * Lowercases, strips punctuation, and collapses whitespace/underscore runs to
 * single dashes (e.g. `"Acme, Inc."` → `"acme-inc"`).
 *
 * @param name The organization display name to derive from.
 * @returns The derived slug; empty string when the name has no usable characters.
 */
export function generateTenantSlug(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * Validate a candidate tenant slug.
 *
 * @param slug The candidate slug (already trimmed/lowercased by the caller).
 * @returns A human-readable error message, or `null` when the slug is valid.
 */
export function validateTenantSlug(slug: string): string | null {
  if (!slug?.trim()) return 'Tenant slug is required';
  const s = slug.trim().toLowerCase();
  if (s.length < 2) return 'Slug must be at least 2 characters';
  if (!SLUG_REGEX.test(s)) return 'Slug must contain only lowercase letters, numbers, and dashes';
  return null;
}
