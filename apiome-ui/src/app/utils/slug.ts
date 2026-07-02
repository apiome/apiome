/**
 * Utility functions for handling slug input and validation
 */

/**
 * Filters a string to only allow characters valid in a slug (a-z, 0-9, and -)
 * @param value The input string to filter
 * @returns The filtered string containing only valid slug characters
 */
export function filterSlugInput(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '');
}

/**
 * Generates a slug from a name string
 * @param name The name to convert to a slug
 * @returns A URL-friendly slug
 */
export function generateSlug(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

/**
 * Validates if a string is a valid slug
 * @param slug The string to validate
 * @returns True if the slug is valid, false otherwise
 */
export function isValidSlug(slug: string): boolean {
  return /^[a-z0-9-]+$/.test(slug);
}

