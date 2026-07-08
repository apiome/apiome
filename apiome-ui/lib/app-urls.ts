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

/** Commercial studio base URL — resolved at call time for correct env in tests and SSR. */
export function getStudioAppUrl(): string {
  const configured = process.env.NEXT_PUBLIC_STUDIO_URL?.trim();
  return normalizePublicAppUrl(configured || DEFAULT_STUDIO_APP_URL);
}

/** @deprecated Prefer getStudioAppUrl() — resolved at module load. */
export const STUDIO_APP_URL = getStudioAppUrl();
