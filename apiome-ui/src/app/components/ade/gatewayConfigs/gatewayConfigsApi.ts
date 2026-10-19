/**
 * Browser calls for gateway configs (CDG-5.3, #5981), through `/api/gateway-configs`.
 */

import type { GatewayConfig } from '@lib/gateway-configs';

/** Read a proxy answer, or throw its message. */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  return body as T;
}

/** One gateway config, by slug or id, with the APIs it serves. */
export async function fetchGatewayConfig(ref: string): Promise<GatewayConfig> {
  return readJson<GatewayConfig>(
    await fetch(`/api/gateway-configs/${encodeURIComponent(ref)}`, { cache: 'no-store' }),
    'Could not load the gateway config',
  );
}

/** A connector's gateway configs (one per environment). */
export async function fetchConnectorGatewayConfigs(connectorId: string): Promise<GatewayConfig[]> {
  const body = await readJson<{ gatewayConfigs?: GatewayConfig[] }>(
    await fetch(`/api/gateway-configs?connector=${encodeURIComponent(connectorId)}`, { cache: 'no-store' }),
    'Could not load the environments',
  );
  return Array.isArray(body.gatewayConfigs) ? body.gatewayConfigs : [];
}
