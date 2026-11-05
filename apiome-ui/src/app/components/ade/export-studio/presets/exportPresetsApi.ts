/**
 * Client contract for export presets (MFX-39.3, #4335).
 *
 * The screens talk to the `/api/export/presets` proxy, which forwards to the REST layer's
 * `/v1/export/{tenant}/presets` with the session's tenant. Errors are
 * {@link DeliveryProfilesError}s carrying the REST refusal's code and every problem it listed.
 */

import { deliveryApi } from '../delivery/deliveryProfilesApi';
import type { ExportPreset } from './exportPresetsModel';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/** The workspace's export presets, by name. */
export async function fetchExportPresets(): Promise<ExportPreset[]> {
  const data = await deliveryApi<{ presets?: ExportPreset[] }>('/api/export/presets');
  return Array.isArray(data?.presets) ? data.presets : [];
}

/** Store a new preset. */
export function createExportPreset(body: Record<string, unknown>): Promise<ExportPreset> {
  return deliveryApi<ExportPreset>('/api/export/presets', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Change a preset (by id). */
export function updateExportPreset(id: string, body: Record<string, unknown>): Promise<ExportPreset> {
  return deliveryApi<ExportPreset>(`/api/export/presets/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Delete a preset (by id). */
export async function deleteExportPreset(id: string): Promise<void> {
  await deliveryApi<unknown>(`/api/export/presets/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export { DeliveryProfilesError as ExportPresetsError } from '../delivery/deliveryProfilesApi';
