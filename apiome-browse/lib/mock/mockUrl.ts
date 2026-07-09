/**
 * Mock-server URL helpers — SIM-2.3 (#4444).
 *
 * Framework-free logic behind the "Mock available" surfacing on public version pages: the mock
 * base URL, a ready-to-copy curl one-liner, and a sample-path picker that derives a representative
 * operation path from a parsed OpenAPI document. Kept free of React/DOM so it is unit-testable
 * under the browse Vitest setup (which only runs `lib/**` tests).
 *
 * The base-URL shape mirrors the canonical REST builder `_mock_base_url` (apiome-rest
 * `versions_routes.py`, #4422) and the Control Panel's `getMockUrl` (#4443):
 * `{mockHost}/{tenant}/{project}/{version}` — where `mockHost` is
 * `APIOME_MOCK_PUBLIC_BASE_URL` and apiome-mock serves `/{tenant}/{project}/{version}/{path}`.
 */

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Build the public mock base URL for a published version.
 *
 * @param mockHost - The browser-reachable mock host (`APIOME_MOCK_PUBLIC_BASE_URL`), with or
 *   without a trailing slash.
 * @param tenantSlug - The owning tenant's slug.
 * @param projectSlug - The owning project's slug.
 * @param versionId - The version label (e.g. `1.0.0`).
 * @returns `{mockHost}/{tenant}/{project}/{version}` with no trailing slash, or `null` when any
 *   part is missing (the caller must additionally gate on the version's `mock_enabled` flag).
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

/**
 * Build the copyable curl one-liner that hits the mock.
 *
 * @param mockBaseUrl - The version's mock base URL (from {@link buildMockBaseUrl}).
 * @param samplePath - An operation path to request (default `/`); a missing leading slash is added.
 * @returns A `curl <url>` command string.
 */
export function mockCurlCommand(mockBaseUrl: string, samplePath: string = '/'): string {
  const base = mockBaseUrl.replace(/\/+$/, '');
  const path = samplePath.startsWith('/') ? samplePath : `/${samplePath}`;
  return `curl ${base}${path}`;
}

const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace'];

/**
 * Pick a representative operation path from a parsed OpenAPI document for the curl one-liner.
 *
 * Preference order: the first path (in document order) with a GET operation and no `{parameters}`,
 * then the first path with a GET operation, then the first path with any HTTP operation, and
 * finally `/` when the document has no usable paths (or is not an OpenAPI object at all).
 *
 * @param spec - The parsed spec document (`unknown`; safely inspected).
 * @returns An operation path starting with `/`.
 */
export function sampleMockPath(spec: unknown): string {
  if (!isObject(spec) || !isObject(spec.paths)) return '/';

  let firstGetPath: string | undefined;
  let firstOpPath: string | undefined;
  for (const [path, item] of Object.entries(spec.paths)) {
    if (!isObject(item)) continue;
    if (isObject(item.get)) {
      if (!path.includes('{')) return path.startsWith('/') ? path : `/${path}`;
      firstGetPath ??= path;
    } else if (HTTP_METHODS.some((m) => isObject(item[m]))) {
      firstOpPath ??= path;
    }
  }
  const chosen = firstGetPath ?? firstOpPath;
  if (!chosen) return '/';
  return chosen.startsWith('/') ? chosen : `/${chosen}`;
}
