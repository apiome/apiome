/**
 * Browser calls for the agent and model pages (CDG-5.2, #5980), through `/api/catalog-agents` and
 * `/api/catalog-models`, plus the agent-key list the **Link key** dialog offers (AGX-3.4 BFF).
 */

import type { CatalogAgent, CatalogModel } from '@lib/catalog-agents';

/**
 * Read a proxy answer, or throw its message.
 *
 * @param response - The proxy response.
 * @param fallback - The message when the answer carries none.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  if (response.status === 204) return undefined as T;
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

/** A JSON write. */
function write(url: string, method: string, body?: unknown): Promise<Response> {
  return fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

const agentUrl = (ref: string) => `/api/catalog-agents/${encodeURIComponent(ref)}`;
const modelUrl = (ref: string) => `/api/catalog-models/${encodeURIComponent(ref)}`;

/** One agent, by slug or id. */
export async function fetchAgent(ref: string): Promise<CatalogAgent> {
  return readJson<CatalogAgent>(await fetch(agentUrl(ref), { cache: 'no-store' }), 'Could not load the agent');
}

/** What registering an agent sends. */
export interface AgentDraft {
  name: string;
  slug?: string;
  description?: string;
  runtime?: string;
  model?: string | null;
  keyIds?: string[];
}

/** Register an agent. */
export async function createAgent(draft: AgentDraft): Promise<CatalogAgent> {
  return readJson<CatalogAgent>(await write('/api/catalog-agents', 'POST', draft), 'Could not register the agent');
}

/** Change an agent (an omitted field is kept; `model: null` clears it). */
export async function updateAgent(
  ref: string,
  change: Partial<{ name: string; description: string | null; runtime: string | null; model: string | null; status: string }>,
): Promise<CatalogAgent> {
  return readJson<CatalogAgent>(await write(agentUrl(ref), 'PATCH', change), 'Could not save the agent');
}

/** Delete an agent. */
export async function deleteAgent(ref: string): Promise<void> {
  await readJson<void>(await write(agentUrl(ref), 'DELETE'), 'Could not delete the agent');
}

/** Link an agent key. */
export async function linkAgentKey(ref: string, keyId: string): Promise<CatalogAgent> {
  return readJson<CatalogAgent>(
    await write(`${agentUrl(ref)}/keys/${encodeURIComponent(keyId)}`, 'PUT'),
    'Could not link the key',
  );
}

/** Unlink an agent key. */
export async function unlinkAgentKey(ref: string, keyId: string): Promise<CatalogAgent> {
  return readJson<CatalogAgent>(
    await write(`${agentUrl(ref)}/keys/${encodeURIComponent(keyId)}`, 'DELETE'),
    'Could not unlink the key',
  );
}

/** The workspace's live models. */
export async function fetchModels(): Promise<CatalogModel[]> {
  const body = await readJson<{ models?: CatalogModel[] }>(
    await fetch('/api/catalog-models', { cache: 'no-store' }),
    'Could not load the models',
  );
  return Array.isArray(body.models) ? body.models : [];
}

/** One model, by slug or id. */
export async function fetchModel(ref: string): Promise<CatalogModel> {
  return readJson<CatalogModel>(await fetch(modelUrl(ref), { cache: 'no-store' }), 'Could not load the model');
}

/** What registering a model sends. */
export interface ModelDraft {
  name?: string;
  slug?: string;
  provider: string;
  modelName: string;
  modelVersion?: string;
  hosting: string;
  dataHandling?: string;
  deprecatedAt?: string | null;
}

/** Register a model. */
export async function createModel(draft: ModelDraft): Promise<CatalogModel> {
  return readJson<CatalogModel>(await write('/api/catalog-models', 'POST', draft), 'Could not register the model');
}

/** Change a model (`deprecatedAt: null` clears the date). */
export async function updateModel(ref: string, change: Partial<ModelDraft>): Promise<CatalogModel> {
  return readJson<CatalogModel>(await write(modelUrl(ref), 'PATCH', change), 'Could not save the model');
}

/** Delete a model. */
export async function deleteModel(ref: string): Promise<void> {
  await readJson<void>(await write(modelUrl(ref), 'DELETE'), 'Could not delete the model');
}

/** An agent key as the Link key dialog lists it (name, prefix, status — never the secret). */
export interface LinkableKey {
  id: string;
  name: string;
  keyPrefix: string;
  status: string;
}

/** The workspace's live agent keys (AGX-3.1), for the Link key dialog. */
export async function fetchAgentKeys(): Promise<LinkableKey[]> {
  const body = await readJson<{ data?: { keys?: LinkableKey[] } }>(
    await fetch('/api/agent-access/keys', { cache: 'no-store' }),
    'Could not load the agent keys',
  );
  const keys = body.data?.keys;
  return Array.isArray(keys) ? keys.filter((key) => key.status !== 'revoked') : [];
}
