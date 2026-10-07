/**
 * Agent access transport — AGX-3.4 (#4540).
 *
 * Thin `fetch` wrappers over the `/api/agent-access/*` BFF routes, which forward to apiome-rest
 * under the session's tenant. Every function resolves with parsed model types or throws an
 * {@link AgentAccessError} carrying apiome-rest's message, status and stable refusal code.
 */

import { getPublishedVersionsForTenant } from '@lib/db/helper';

import {
  parseAgentKey,
  parseAgentKeyList,
  parseAgentKeyUsage,
  parseAgentTool,
  parseAgentToolset,
  parseAgentToolsetList,
  parseAgentUsage,
  parsePublishedVersionOptions,
  type AgentKey,
  type AgentKeyUsage,
  type AgentTool,
  type AgentToolsetDetail,
  type AgentToolsetTarget,
  type AgentUsage,
  type PublishedVersionOption,
} from './agentAccessModel';

/** The BFF prefix. */
const BASE = '/api/agent-access';

/** A refused or failed agent-access call. */
export class AgentAccessError extends Error {
  /** The HTTP status (0 when the request never got an answer). */
  readonly status: number;

  /** apiome-rest's stable refusal code, e.g. `agent-toolset-write-op-unconfirmed`. */
  readonly code: string | null;

  /**
   * @param message - What went wrong, fit to show.
   * @param status - The HTTP status.
   * @param code - The refusal code, when there is one.
   */
  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = 'AgentAccessError';
    this.status = status;
    this.code = code;
  }
}

/**
 * Call one BFF route and unwrap `{success, data}`.
 *
 * @param path - The path under `/api/agent-access`.
 * @param init - `method` and JSON `body`.
 * @returns The `data` of a successful reply.
 * @throws AgentAccessError on a refusal or an unreadable reply.
 */
async function call(
  path: string,
  init: { method?: string; body?: unknown } = {}
): Promise<unknown> {
  const response = await fetch(`${BASE}${path}`, {
    method: init.method ?? 'GET',
    credentials: 'include',
    headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  let payload: { success?: boolean; data?: unknown; error?: unknown; code?: unknown } = {};
  try {
    payload = (await response.json()) as typeof payload;
  } catch {
    payload = {};
  }
  // The BFF's `{success}` envelope is the verdict: every route answers with it, success or not.
  if (payload.success !== true) {
    throw new AgentAccessError(
      typeof payload.error === 'string' && payload.error ? payload.error : 'Request failed',
      response.status,
      typeof payload.code === 'string' ? payload.code : null
    );
  }
  return payload.data;
}

/** The tenant's toolsets, newest first. */
export async function fetchToolsets(): Promise<AgentToolsetDetail[]> {
  return parseAgentToolsetList(await call('/toolsets'));
}

/**
 * One toolset with every tool.
 *
 * @param toolsetId - The toolset.
 */
export async function fetchToolset(toolsetId: string): Promise<AgentToolsetDetail> {
  return parseAgentToolset(await call(`/toolsets/${encodeURIComponent(toolsetId)}`));
}

/**
 * Enable Agent Access for a published version.
 *
 * @param versionId - The `versions.id`.
 * @param target - Where calls go.
 * @returns The seeded toolset (reads enabled, writes disabled).
 */
export async function createToolset(
  versionId: string,
  target: AgentToolsetTarget
): Promise<AgentToolsetDetail> {
  return parseAgentToolset(
    await call('/toolsets', { method: 'POST', body: { versionId, target, enabled: true } })
  );
}

/**
 * Change a toolset's settings.
 *
 * @param toolsetId - The toolset.
 * @param patch - `enabled` and/or `target`.
 * @returns The toolset's settings after the change (without tools).
 */
export async function updateToolset(
  toolsetId: string,
  patch: { enabled?: boolean; target?: AgentToolsetTarget }
): Promise<AgentToolsetDetail> {
  return parseAgentToolset(
    await call(`/toolsets/${encodeURIComponent(toolsetId)}`, { method: 'PATCH', body: patch })
  );
}

/**
 * Delete a toolset — and, with it, its agent keys and upstream credentials.
 *
 * @param toolsetId - The toolset.
 */
export async function deleteToolset(toolsetId: string): Promise<void> {
  await call(`/toolsets/${encodeURIComponent(toolsetId)}`, { method: 'DELETE' });
}

/**
 * Enable or disable one tool.
 *
 * @param toolsetId - The toolset.
 * @param toolId - The tool row.
 * @param enabled - The new state.
 * @param confirmWriteOp - The explicit confirmation a write op needs to be enabled.
 * @returns The tool after the change.
 */
export async function setToolEnabled(
  toolsetId: string,
  toolId: string,
  enabled: boolean,
  confirmWriteOp = false
): Promise<AgentTool> {
  return parseAgentTool(
    await call(
      `/toolsets/${encodeURIComponent(toolsetId)}/tools/${encodeURIComponent(toolId)}`,
      { method: 'PATCH', body: confirmWriteOp ? { enabled, confirmWriteOp } : { enabled } }
    )
  );
}

/**
 * The tenant's agent keys.
 *
 * @param includeRevoked - Whether to list revoked keys too.
 */
export async function fetchAgentKeys(includeRevoked: boolean): Promise<AgentKey[]> {
  const qs = includeRevoked ? '?includeRevoked=true' : '';
  return parseAgentKeyList(await call(`/keys${qs}`));
}

/**
 * Mint an agent key.
 *
 * @param body - The create body (see `agentKeyCreateBody`).
 * @returns The key's metadata and its one-time secret. The secret is returned separately so it
 *   never lands in a list of keys.
 */
export async function createAgentKey(
  body: Record<string, unknown>
): Promise<{ key: AgentKey; secret: string }> {
  const data = await call('/keys', { method: 'POST', body });
  const secret = (data as { secret?: unknown } | null)?.secret;
  if (typeof secret !== 'string' || !secret) {
    throw new AgentAccessError('The key was created but no secret came back.', 502);
  }
  return { key: parseAgentKey(data), secret };
}

/**
 * Replace a key's tool allowlist.
 *
 * @param keyId - The key.
 * @param toolAllowlist - The new list.
 * @returns The key after the change.
 */
export async function updateAgentKeyAllowlist(
  keyId: string,
  toolAllowlist: string[]
): Promise<AgentKey> {
  return parseAgentKey(
    await call(`/keys/${encodeURIComponent(keyId)}/allowlist`, {
      method: 'PUT',
      body: { toolAllowlist },
    })
  );
}

/**
 * Revoke a key (idempotent).
 *
 * @param keyId - The key.
 */
export async function revokeAgentKey(keyId: string): Promise<void> {
  await call(`/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
}

/**
 * One key's usage today against its caps.
 *
 * @param keyId - The key.
 */
export async function fetchAgentKeyUsage(keyId: string): Promise<AgentKeyUsage> {
  return parseAgentKeyUsage(await call(`/keys/${encodeURIComponent(keyId)}/usage`));
}

/**
 * The tenant's usage rollups.
 *
 * @param days - The window, in days.
 */
export async function fetchAgentUsage(days: number): Promise<AgentUsage> {
  return parseAgentUsage(await call(`/usage?days=${encodeURIComponent(String(days))}`));
}

/**
 * The tenant's published versions, for the "Enable Agent Access" picker.
 *
 * @param tenantId - The session's tenant.
 * @returns The versions, newest published first.
 * @throws AgentAccessError when they could not be read.
 */
export async function fetchPublishedVersions(tenantId: string): Promise<PublishedVersionOption[]> {
  const payload = JSON.parse(await getPublishedVersionsForTenant(tenantId)) as {
    success?: boolean;
    error?: string;
  };
  if (!payload.success) {
    throw new AgentAccessError(payload.error || 'Failed to load published versions. Refresh the page to try again.', 500);
  }
  return parsePublishedVersionOptions(payload);
}
