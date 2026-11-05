/**
 * Client contract for export delivery profiles and deliveries (MFX-38.4, #4331).
 *
 * The screens talk to the `/api/export/delivery-profiles`, `/api/export/jobs/{jobId}/deliveries` and
 * `/api/export/storage-credentials` proxies, which forward to the REST layer's `/v1/export/{tenant}/…`
 * routes with the session's tenant — the browser never names it. Each answers `{ success, data }`, or
 * `{ success: false, error, code?, errors? }`.
 */

import type { DeliveryAttempt, DeliveryChannel, DeliveryProfile } from './deliveryProfilesModel';

/** An error carrying the REST refusal's code and every per-field problem it listed. */
export class DeliveryProfilesError extends Error {
  readonly code: string | null;
  readonly errors: string[];

  constructor(message: string, code: string | null = null, errors: string[] = []) {
    super(message);
    this.name = 'DeliveryProfilesError';
    this.code = code;
    this.errors = errors;
  }
}

/**
 * Call one of the export delivery / preset proxies.
 *
 * @param path The proxy path (starting `/api/`).
 * @param init Fetch options.
 * @returns The envelope's `data`.
 * @throws DeliveryProfilesError When the request failed.
 */
export async function deliveryApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'include', ...init });
  const json = (await res.json().catch(() => ({}))) as {
    success?: boolean;
    data?: unknown;
    error?: unknown;
    code?: unknown;
    errors?: unknown;
  };
  if (!json.success) {
    throw new DeliveryProfilesError(
      typeof json.error === 'string' && json.error ? json.error : 'Request failed',
      typeof json.code === 'string' ? json.code : null,
      Array.isArray(json.errors) ? json.errors.map(String) : [],
    );
  }
  return json.data as T;
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/**
 * The workspace's delivery profiles, by name.
 *
 * @param channel Only one channel's profiles.
 * @returns The profiles.
 */
export async function fetchDeliveryProfiles(channel?: DeliveryChannel): Promise<DeliveryProfile[]> {
  const query = channel ? `?channel=${encodeURIComponent(channel)}` : '';
  const data = await deliveryApi<{ profiles?: DeliveryProfile[] }>(`/api/export/delivery-profiles${query}`);
  return Array.isArray(data?.profiles) ? data.profiles : [];
}

/** Store a new profile. */
export function createDeliveryProfile(body: Record<string, unknown>): Promise<DeliveryProfile> {
  return deliveryApi<DeliveryProfile>('/api/export/delivery-profiles', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Change a profile's name, description or destination. */
export function updateDeliveryProfile(id: string, body: Record<string, unknown>): Promise<DeliveryProfile> {
  return deliveryApi<DeliveryProfile>(`/api/export/delivery-profiles/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Delete a profile (its deliveries keep their record). */
export async function deleteDeliveryProfile(id: string): Promise<void> {
  await deliveryApi<unknown>(`/api/export/delivery-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** Every delivery made with one profile, newest first. */
export async function fetchProfileDeliveries(id: string): Promise<DeliveryAttempt[]> {
  const data = await deliveryApi<{ deliveries?: DeliveryAttempt[] }>(
    `/api/export/delivery-profiles/${encodeURIComponent(id)}/deliveries`,
  );
  return Array.isArray(data?.deliveries) ? data.deliveries : [];
}

/** Every delivery of one export job, across channels, newest first. */
export async function fetchJobDeliveries(jobId: string): Promise<DeliveryAttempt[]> {
  const data = await deliveryApi<{ deliveries?: DeliveryAttempt[] }>(
    `/api/export/jobs/${encodeURIComponent(jobId)}/deliveries`,
  );
  return Array.isArray(data?.deliveries) ? data.deliveries : [];
}

/** Deliver a completed export job now with one profile. */
export function deliverJob(jobId: string, profileId: string): Promise<DeliveryAttempt> {
  return deliveryApi<DeliveryAttempt>(`/api/export/jobs/${encodeURIComponent(jobId)}/deliveries`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ profileId }),
  });
}

/** One choice for a reference picker (a repository or a storage credential). */
export interface ReferenceOption {
  id: string;
  label: string;
}

/**
 * The workspace's registered repositories, for a git profile's picker. Never throws: an unreadable
 * list is empty, and the form says so.
 */
export async function fetchRepositoryOptions(): Promise<ReferenceOption[]> {
  try {
    const res = await fetch('/api/repositories', { credentials: 'include' });
    const json = (await res.json()) as { repositories?: Array<Record<string, unknown>> };
    return (json.repositories ?? [])
      .filter((row) => typeof row.id === 'string')
      .map((row) => ({
        id: String(row.id),
        label: String(row.full_name ?? row.fullName ?? row.name ?? row.id),
      }));
  } catch {
    return [];
  }
}

/** The workspace's bucket credentials, for an object-storage profile's picker. Never throws. */
export async function fetchStorageCredentialOptions(): Promise<ReferenceOption[]> {
  try {
    const data = await deliveryApi<{ credentials?: Array<Record<string, unknown>> }>(
      '/api/export/storage-credentials',
    );
    return (data?.credentials ?? [])
      .filter((row) => typeof row.id === 'string')
      .map((row) => ({
        id: String(row.id),
        label: `${String(row.name ?? row.id)} (…${String(row.accessKeyHint ?? '')})`,
      }));
  } catch {
    return [];
  }
}
