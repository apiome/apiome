/**
 * Browser calls for the **Verification settings** and **Re-publish requests** pages (PFX-6.2,
 * #6954), through the `/api/pact/*` proxies.
 *
 * Each throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", a 409 says the request closed, a 422 names the field).
 */

import type {
  OverrideBody,
  OverrideRecord,
  RepublishRequest,
  RepublishRequestPage,
  SettingsBody,
  VerificationSettings,
} from '@lib/pact-remediation';
import { readJson } from '../pactPacticipants/pacticipantsApi';

const SETTINGS = '/api/pact/verification-settings';
const REQUESTS = '/api/pact/republish-requests';

/** JSON request options for a write. */
function write(method: 'PUT' | 'POST' | 'DELETE', body?: unknown): RequestInit {
  return {
    method,
    cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  };
}

/**
 * The workspace's verification settings.
 *
 * @returns The settings (the defaults when never saved).
 */
export async function fetchSettings(): Promise<VerificationSettings> {
  return readJson<VerificationSettings>(await fetch(SETTINGS, { cache: 'no-store' }), 'Could not load the settings');
}

/**
 * Save the workspace's verification settings.
 *
 * @param body - Every field.
 * @returns The stored settings.
 */
export async function saveSettings(body: SettingsBody): Promise<VerificationSettings> {
  return readJson<VerificationSettings>(await fetch(SETTINGS, write('PUT', body)), 'Could not save the settings');
}

/**
 * Every override of the workspace.
 *
 * @returns The overrides, provider-wide first.
 */
export async function fetchOverrides(): Promise<OverrideRecord[]> {
  const body = await readJson<{ overrides?: OverrideRecord[] }>(
    await fetch(`${SETTINGS}/overrides`, { cache: 'no-store' }),
    'Could not load the overrides',
  );
  return Array.isArray(body.overrides) ? body.overrides : [];
}

/**
 * Create or replace a provider-wide or per-pair override.
 *
 * @param body - The override.
 * @returns The stored override.
 */
export async function saveOverride(body: OverrideBody): Promise<OverrideRecord> {
  return readJson<OverrideRecord>(
    await fetch(`${SETTINGS}/overrides`, write('PUT', body)),
    'Could not save the override',
  );
}

/**
 * Remove an override.
 *
 * @param id - The override's id.
 */
export async function removeOverride(id: string): Promise<void> {
  const response = await fetch(`${SETTINGS}/overrides/${encodeURIComponent(id)}`, write('DELETE'));
  if (!response.ok) await readJson<unknown>(response, 'Could not remove the override');
}

/**
 * One page of re-publish requests.
 *
 * @param filters - `state` (a state or `open`), `provider`, and the previous page's `cursor`.
 * @returns The page.
 */
export async function fetchRequests(
  filters: { state?: string | null; provider?: string | null; cursor?: string | null } = {},
): Promise<RepublishRequestPage> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
  const rendered = query.toString();
  const body = await readJson<RepublishRequestPage>(
    await fetch(`${REQUESTS}${rendered ? `?${rendered}` : ''}`, { cache: 'no-store' }),
    'Could not load the re-publish requests',
  );
  return { requests: Array.isArray(body.requests) ? body.requests : [], next_cursor: body.next_cursor ?? null };
}

/**
 * One re-publish request.
 *
 * @param id - The request's id.
 * @returns The request.
 */
export async function fetchRequest(id: string): Promise<RepublishRequest> {
  return readJson<RepublishRequest>(
    await fetch(`${REQUESTS}/${encodeURIComponent(id)}`, { cache: 'no-store' }),
    'Could not load the re-publish request',
  );
}

/**
 * Acknowledge an open re-publish request.
 *
 * @param id - The request's id.
 * @param note - What the consumer will do, and when (optional).
 * @returns The request.
 */
export async function acknowledgeRequest(id: string, note: string): Promise<RepublishRequest> {
  return readJson<RepublishRequest>(
    await fetch(
      `${REQUESTS}/${encodeURIComponent(id)}/acknowledge`,
      write('POST', note.trim() ? { note: note.trim() } : {}),
    ),
    'Could not acknowledge the request',
  );
}
