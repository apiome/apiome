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
 * Replace the origin in a REST-computed mock URL with the UI-configured public base URL.
 * REST may use its own `APIOME_MOCK_PUBLIC_BASE_URL`; the Control Panel should honour the UI env.
 */
export function rewriteMockUrlHost(mockUrl: string | null | undefined): string | null {
  if (!mockUrl) return null;
  const host = getMockPublicBaseUrl();
  try {
    const { pathname } = new URL(mockUrl);
    return `${host}${pathname}`;
  } catch {
    return mockUrl;
  }
}

type VersionLike = Record<string, unknown>;

function readString(version: VersionLike, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = version[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  return null;
}

function readBoolean(version: VersionLike, ...keys: string[]): boolean {
  for (const key of keys) {
    if (typeof version[key] === 'boolean') return version[key] as boolean;
  }
  return false;
}

/**
 * Apply the UI mock public base URL to a REST version payload (list/get/toggle responses).
 */
export function applyUiMockBaseUrl<T extends VersionLike>(version: T, tenantSlug: string): T {
  const mockEnabled = readBoolean(version, 'mockEnabled', 'mock_enabled');
  if (!mockEnabled) {
    return { ...version, mockBaseUrl: null, mock_base_url: null };
  }

  const published = readBoolean(version, 'published');
  const mockPrivate = readBoolean(version, 'mockPrivate', 'mock_private');
  if (!published && !mockPrivate) {
    return { ...version, mockBaseUrl: null, mock_base_url: null };
  }

  const fromRest = rewriteMockUrlHost(readString(version, 'mockBaseUrl', 'mock_base_url'));
  const projectSlug = readString(version, 'projectSlug', 'project_slug');
  const versionLabel = readString(version, 'versionId', 'version_id');
  const mockBaseUrl =
    fromRest ??
    (projectSlug && versionLabel
      ? buildMockBaseUrl(getMockPublicBaseUrl(), tenantSlug, projectSlug, versionLabel)
      : null);

  return { ...version, mockBaseUrl, mock_base_url: mockBaseUrl };
}

export function applyUiMockBaseUrls(versions: unknown[], tenantSlug: string): unknown[] {
  return versions.map((version) =>
    version && typeof version === 'object'
      ? applyUiMockBaseUrl(version as VersionLike, tenantSlug)
      : version
  );
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
