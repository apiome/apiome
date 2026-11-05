/**
 * The Registry destination's fetches (MFX-46.3). The connectors come from `/api/connectors` (the
 * workspace's catalog connectors, managed on Connectors); the push goes through `/api/export/registry-push`,
 * which scopes it to the signed-in workspace.
 */

import { deliveryApi } from './deliveryProfilesApi';
import type { RegistryConnector, RegistryPushResult } from './registryPushModel';

/** The workspace's `schema-registry` connectors. */
export async function fetchRegistryConnectors(): Promise<RegistryConnector[]> {
  const res = await fetch('/api/connectors', { credentials: 'include' });
  const json = (await res.json().catch(() => ({}))) as {
    connectors?: Array<{ id?: unknown; kind?: unknown; name?: unknown; baseUrl?: unknown }>;
  };
  if (!res.ok || !Array.isArray(json.connectors)) return [];
  return json.connectors
    .filter((connector) => connector.kind === 'schema-registry' && typeof connector.id === 'string')
    .map((connector) => ({
      id: String(connector.id),
      name: typeof connector.name === 'string' && connector.name ? connector.name : String(connector.id),
      baseUrl: typeof connector.baseUrl === 'string' ? connector.baseUrl : null,
    }));
}

/**
 * Push the export to a schema registry.
 *
 * @param body The `schema-registry/push` body (see `registryPushBody`).
 * @returns What happened to each subject.
 */
export function pushToRegistry(body: Record<string, unknown>): Promise<RegistryPushResult> {
  return deliveryApi<RegistryPushResult>('/api/export/registry-push', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
