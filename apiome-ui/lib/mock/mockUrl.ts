/**
 * Mock-server URL helpers — mirrors apiome-browse `lib/mock/mockUrl.ts` and REST
 * `_mock_base_url` (apiome-rest `versions_routes.py`, #4422).
 */

const DEFAULT_MOCK_PUBLIC_BASE_URL = 'http://localhost:8775';

/**
 * Browser-reachable mock host from `APIOME_MOCK_PUBLIC_BASE_URL` (no trailing slash).
 * Read on the server at request time — not a `NEXT_PUBLIC_*` var.
 */
export function getMockPublicBaseUrl(): string {
  return (process.env.APIOME_MOCK_PUBLIC_BASE_URL || DEFAULT_MOCK_PUBLIC_BASE_URL).replace(/\/+$/, '');
}

/**
 * Build the public mock base URL for a published version.
 *
 * @returns `{mockHost}/{tenant}/{project}/{version}` or `null` when any part is missing.
 */
export function buildMockBaseUrl(
  mockHost: string,
  tenantSlug: string,
  projectSlug: string,
  versionId: string
): string | null {
  const host = (mockHost || '').replace(/\/+$/, '');
  if (!host || !tenantSlug || !projectSlug || !versionId) return null;
  return `${host}/${tenantSlug}/${projectSlug}/${versionId}`;
}
