/**
 * Browser calls for **Settings → Secrets**, **CI and commit statuses** and **Agents** (PFX-8.15,
 * #7312), through the `/api/pact/*` proxies. Each throws REST's message on a failure, so the tab can
 * show it (a 403 reads "Permission denied", a 409 names what uses a secret).
 */

import type {
  AgentSettings,
  CommitStatusSettings,
  ContractSettings,
  SecretList,
  SecretRecord,
} from '@lib/pact-contract-settings';
import { readJson } from '../pactPacticipants/pacticipantsApi';

/** JSON request options for a write. */
function send(method: 'PUT' | 'POST' | 'DELETE', body?: unknown): RequestInit {
  return {
    method,
    cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  };
}

/** Both groups of switches, with `can_edit`. */
export async function fetchContractSettings(): Promise<ContractSettings> {
  return readJson<ContractSettings>(
    await fetch('/api/pact/contract-settings', { cache: 'no-store' }),
    'Could not load the settings',
  );
}

/**
 * Save the commit-status switches.
 *
 * @param switches - All three.
 * @returns Both groups as stored.
 */
export async function saveCommitStatuses(switches: CommitStatusSettings): Promise<ContractSettings> {
  return readJson<ContractSettings>(
    await fetch('/api/pact/contract-settings/commit-statuses', send('PUT', switches)),
    'Could not save the commit-status switches',
  );
}

/**
 * Save the agent switches.
 *
 * @param switches - All four.
 * @returns Both groups as stored.
 */
export async function saveAgents(switches: AgentSettings): Promise<ContractSettings> {
  return readJson<ContractSettings>(
    await fetch('/api/pact/contract-settings/agents', send('PUT', switches)),
    'Could not save what agents may do',
  );
}

/** Every secret of the workspace, never a value. */
export async function fetchSecrets(): Promise<SecretList> {
  const list = await readJson<SecretList>(await fetch('/api/pact/secrets', { cache: 'no-store' }), 'Could not load the secrets');
  return { ...list, secrets: Array.isArray(list.secrets) ? list.secrets : [] };
}

/**
 * Create a secret.
 *
 * @param body - Its name, value and optional description.
 * @returns The stored secret, without its value.
 */
export async function createSecret(body: { name: string; value: string; description?: string }): Promise<SecretRecord> {
  return readJson<SecretRecord>(await fetch('/api/pact/secrets', send('POST', body)), 'Could not save the secret');
}

/**
 * Replace (or set) a secret's value.
 *
 * @param id - The secret.
 * @param value - The new value.
 * @param description - Its description, kept as it is.
 * @returns The stored secret, without its value.
 */
export async function setSecretValue(id: string, value: string, description?: string | null): Promise<SecretRecord> {
  return readJson<SecretRecord>(
    await fetch(`/api/pact/secrets/${encodeURIComponent(id)}`, send('PUT', { value, description: description ?? null })),
    'Could not save the value',
  );
}

/**
 * Delete a secret nothing uses.
 *
 * @param id - The secret.
 */
export async function deleteSecret(id: string): Promise<void> {
  const response = await fetch(`/api/pact/secrets/${encodeURIComponent(id)}`, send('DELETE'));
  if (!response.ok) await readJson<unknown>(response, 'Could not delete the secret');
}

/** The workspace's `PACT_BROKER_BASE_URL`. */
export async function fetchBrokerAddress(): Promise<string> {
  const body = await readJson<{ broker_base_url: string }>(
    await fetch('/api/pact/broker-address', { cache: 'no-store' }),
    'Could not read the broker address',
  );
  return body.broker_base_url;
}
