const DEFAULT_BROWSE_APP_URL = 'https://browse.apiome.dev';
const DEFAULT_STUDIO_APP_URL = 'https://suite.apiome.dev';
const DEFAULT_MAIN_APP_URL = 'https://main.apiome.dev';

/** Normalize external app URLs to a trailing slash for consistent linking. */
export function normalizePublicAppUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed) return `${DEFAULT_BROWSE_APP_URL}/`;
  return `${trimmed.replace(/\/+$/, '')}/`;
}

/** Public apiome-browse base URL (NEXT_PUBLIC_ for client-side links). */
export const BROWSE_APP_URL = normalizePublicAppUrl(
  process.env.NEXT_PUBLIC_BROWSE_URL || DEFAULT_BROWSE_APP_URL
);

/** Commercial studio base URL — resolved at call time for correct env in tests and SSR. */
export function getStudioAppUrl(): string {
  const configured = process.env.NEXT_PUBLIC_STUDIO_URL?.trim();
  return normalizePublicAppUrl(configured || DEFAULT_STUDIO_APP_URL);
}

/** @deprecated Prefer getStudioAppUrl() — resolved at module load. */
export const STUDIO_APP_URL = getStudioAppUrl();

/**
 * Normalize an app origin by stripping trailing slashes, falling back when blank.
 *
 * @param url - Configured origin, possibly empty or whitespace.
 * @param fallback - Origin to use when `url` carries no value.
 * @returns The origin without a trailing slash.
 */
export function normalizeAppOrigin(url: string, fallback: string): string {
  const trimmed = url.trim();
  if (!trimmed) return fallback.replace(/\/+$/, '');
  return trimmed.replace(/\/+$/, '');
}

/**
 * Main (platform) app base URL — resolved at call time so tests and SSR see
 * the current env. Unlike the studio/browse URLs this has no trailing slash,
 * because callers append absolute paths to it.
 *
 * @returns The main app origin, e.g. `https://main.apiome.dev`.
 */
export function getMainAppUrl(): string {
  return normalizeAppOrigin(process.env.NEXT_PUBLIC_MAIN_APP_URL || '', DEFAULT_MAIN_APP_URL);
}
