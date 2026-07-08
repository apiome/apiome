const DEFAULT_BROWSE_APP_URL = 'https://browse.apiome.app';
const DEFAULT_STUDIO_APP_URL = 'https://studio.apiome.app';

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

/** Commercial studio base URL (NEXT_PUBLIC_ for client-side links). */
export const STUDIO_APP_URL = normalizePublicAppUrl(
  process.env.NEXT_PUBLIC_STUDIO_URL || DEFAULT_STUDIO_APP_URL
);
