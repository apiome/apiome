/**
 * Search input normalization for the public browse catalog.
 * Queries are passed only as bound parameters; LIKE wildcards are escaped server-side.
 */

/** @deprecated Prefer removing the HTML pattern attribute — catalog search allows path punctuation. */
export const SAFE_SEARCH_HTML_PATTERN = '.*';

export const CATALOG_SEARCH_MAX_LENGTH = 256;

/**
 * Validates length and absence of control characters (except tab/newline stripped).
 */
export function isValidSearchInput(value: string): boolean {
  return value.length <= CATALOG_SEARCH_MAX_LENGTH && !/[\x00-\x08\x0B\x0C\x0E-\x1F]/.test(value);
}

/**
 * Normalizes user search input: strips control characters and caps length.
 */
export function sanitizeSearchInput(value: string): string {
  return value
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '')
    .slice(0, CATALOG_SEARCH_MAX_LENGTH);
}

