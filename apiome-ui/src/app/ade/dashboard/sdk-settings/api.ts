/**
 * Client contract for SDK generation settings — SDK-3.4 (#4494).
 *
 * The screen talks to the `/api/sdk-settings` proxy, which forwards to the REST layer's
 * `/v1/tenants/{slug}/governance/sdk-generation-settings` (workspace scope) and
 * `/v1/projects/{slug}/{projectRef}/sdk-settings` (project scope). The tenant slug is resolved
 * server-side from the session, so the browser never names it.
 *
 * Types mirror the REST models' camelCase serialization aliases and live in `sdkSettingsModel.ts`
 * beside the form logic that reads them.
 */

import type { SdkSettingsBody, SdkSettingsResponse } from './sdkSettingsModel';

// The project picker and the read-only gate are the same two reads every governance screen makes,
// so they are imported from the style-guides surface that already owns them rather than copied.
export {
  fetchMyPermissions,
  fetchProjectOptions,
  type MyPermissions,
  type ProjectOption,
} from '../style-guides/api';

/** The refusal shape the REST layer returns for an invalid settings body. */
export interface SdkSettingsValidationError {
  code: string;
  errors: string[];
}

/**
 * An error carrying the per-field problems a `422` listed.
 *
 * The REST layer reports *every* problem in one response so a caller fixes them all at once; a
 * plain `Error` would flatten that back into one line.
 */
export class SdkSettingsError extends Error {
  readonly errors: string[];

  constructor(message: string, errors: string[] = []) {
    super(message);
    this.name = 'SdkSettingsError';
    this.errors = errors;
  }
}

/**
 * Call the settings proxy.
 *
 * @param path Sub-path under `/api/sdk-settings` — empty for the workspace scope, the project
 *   reference for a project's.
 * @param init Fetch options.
 * @returns The parsed `data` payload.
 * @throws SdkSettingsError When the request failed; `errors` carries the per-field problems.
 */
export async function sdkSettingsApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/sdk-settings${path ? `/${encodeURIComponent(path)}` : ''}`, init);
  const json = await res.json().catch(() => ({}));
  if (!json.success) {
    const raw = json.error;
    const message =
      typeof raw === 'object' && raw !== null
        ? (raw as { message?: string }).message || 'Request failed'
        : raw || 'Request failed';
    throw new SdkSettingsError(String(message), Array.isArray(json.errors) ? json.errors : []);
  }
  return json.data as T;
}

/**
 * Read the settings in force for a scope.
 *
 * @param projectRef The project's id or slug, or `null` for the workspace defaults.
 * @returns The settings in force.
 */
export function fetchSdkSettings(projectRef: string | null): Promise<SdkSettingsResponse> {
  return sdkSettingsApi<SdkSettingsResponse>(projectRef ?? '');
}

/**
 * Save a scope's settings, replacing whatever it held.
 *
 * @param projectRef The project's id or slug, or `null` for the workspace defaults.
 * @param settings The body to store — only the keys it names are stored.
 * @returns The settings now in force.
 */
export function saveSdkSettings(
  projectRef: string | null,
  settings: SdkSettingsBody,
): Promise<SdkSettingsResponse> {
  return sdkSettingsApi<SdkSettingsResponse>(projectRef ?? '', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings }),
  });
}

/**
 * Drop a scope's saved settings.
 *
 * @param projectRef The project's id or slug, or `null` for the workspace defaults.
 * @returns The settings now in force — what the scope fell back to.
 */
export function clearSdkSettings(projectRef: string | null): Promise<SdkSettingsResponse> {
  return sdkSettingsApi<SdkSettingsResponse>(projectRef ?? '', { method: 'DELETE' });
}
