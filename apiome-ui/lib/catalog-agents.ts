/**
 * Agent and model entities in the UI — CDG-5.2 (#5980).
 *
 * The wire shapes of apiome-rest's `/v1/tenants/{t}/catalog-agents` and `/catalog-models`, the
 * pages that render them, the proxy's path allowlist and the small pure helpers the pages share.
 * An agent key appears only as its name, lookup prefix and status — never its secret.
 */

import type { EntityOwner } from '@lib/owners';

/** An agent is `active` or `retired`; a retired agent consumes nothing. */
export const AGENT_STATUSES = ['active', 'retired'] as const;
export type AgentStatus = (typeof AGENT_STATUSES)[number];

/** Where a model runs. */
export const MODEL_HOSTINGS = ['api', 'self_hosted'] as const;
export type ModelHosting = (typeof MODEL_HOSTINGS)[number];

/** What each hosting value is called. */
export const MODEL_HOSTING_LABELS: Readonly<Record<ModelHosting, string>> = {
  api: "Provider's API",
  self_hosted: 'Self-hosted',
};

/** The model an agent runs on. */
export interface AgentModelRef {
  id: string;
  slug: string;
  name: string;
  provider: string;
  modelVersion: string | null;
  deprecatedAt: string | null;
  /** Whether `deprecatedAt` has arrived. */
  deprecated: boolean;
}

/** An agent key the agent uses — never its secret. */
export interface AgentKeyRef {
  id: string;
  name: string;
  keyPrefix: string;
  status: 'active' | 'disabled' | 'expired' | 'revoked';
  toolsetId: string | null;
  projectId: string | null;
  projectName: string | null;
  versionLabel: string | null;
  enabledTools: number;
  revokedAt: string | null;
  lastUsedAt: string | null;
}

/** The consumer the agent is in one project. */
export interface AgentConsumerRef {
  consumerId: string;
  projectId: string;
  projectName: string | null;
  operationCount: number;
}

/** An agent. */
export interface CatalogAgent {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  runtime: string | null;
  status: AgentStatus;
  model: AgentModelRef | null;
  owner: EntityOwner | null;
  keys: AgentKeyRef[];
  consumers: AgentConsumerRef[];
  usageHref: string;
  createdAt: string | null;
  updatedAt: string | null;
}

/** An agent, as a model lists the agents that run on it. */
export interface AgentRef {
  id: string;
  slug: string;
  name: string;
  status: AgentStatus;
}

/** A model. */
export interface CatalogModel {
  id: string;
  slug: string;
  name: string;
  provider: string;
  modelName: string;
  modelVersion: string | null;
  hosting: ModelHosting;
  dataHandling: string | null;
  deprecatedAt: string | null;
  deprecated: boolean;
  owner: EntityOwner | null;
  agents: AgentRef[];
  createdAt: string | null;
  updatedAt: string | null;
}

/** The page of one agent. */
export function agentHref(slug: string): string {
  return `/ade/dashboard/catalog/agents/${encodeURIComponent(slug)}`;
}

/** The page of one model. */
export function modelHref(slug: string): string {
  return `/ade/dashboard/catalog/models/${encodeURIComponent(slug)}`;
}

/**
 * The deprecation line of a model, or `null` when it has no date.
 *
 * @param model - Anything with `deprecatedAt` and `deprecated`.
 * @returns `Deprecated since 1 Jan 2026` or `Deprecated from 1 Jan 2027`.
 */
export function deprecationLabel(model: { deprecatedAt: string | null; deprecated: boolean }): string | null {
  if (!model.deprecatedAt) return null;
  const when = new Date(model.deprecatedAt).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
  return model.deprecated ? `Deprecated since ${when}` : `Deprecated from ${when}`;
}

/** What each key status is called. */
export const KEY_STATUS_LABELS: Readonly<Record<AgentKeyRef['status'], string>> = {
  active: 'Active',
  disabled: 'Disabled',
  expired: 'Expired',
  revoked: 'Revoked',
};

/** A slug as apiome-rest constrains one. */
const SLUG = /^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$/;

/** An id (UUID) — an owned entity on a team page links by id. */
const UUID = /^[0-9a-fA-F-]{36}$/;

/** A slug or an id, as the detail routes accept. */
export function isEntityRef(value: string): boolean {
  return SLUG.test(value) || UUID.test(value);
}

/** HTTP methods the proxies forward. */
export type CatalogAgentMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

/**
 * The REST path (below `/v1/tenants/{slug}`) a proxy request may reach, or `null`.
 *
 * | Path | Methods |
 * | --- | --- |
 * | `catalog-agents`, `catalog-models` | GET, POST |
 * | `catalog-agents/{slug}`, `catalog-models/{slug}` | GET, PATCH, DELETE |
 * | `catalog-agents/{slug}/keys/{keyId}` | PUT, DELETE |
 *
 * @param collection - `catalog-agents` or `catalog-models`.
 * @param segments - The decoded path segments after the collection.
 * @param method - The request method.
 */
export function catalogAgentProxyPath(
  collection: 'catalog-agents' | 'catalog-models',
  segments: readonly string[],
  method: CatalogAgentMethod,
): string | null {
  const [ref, sub, keyId, ...rest] = segments;
  if (rest.length > 0) return null;
  if (segments.length === 0) return method === 'GET' || method === 'POST' ? collection : null;
  if (!isEntityRef(ref)) return null;
  const base = `${collection}/${encodeURIComponent(ref)}`;
  if (segments.length === 1) return method === 'GET' || method === 'PATCH' || method === 'DELETE' ? base : null;
  if (collection === 'catalog-agents' && sub === 'keys' && segments.length === 3 && UUID.test(keyId)) {
    return method === 'PUT' || method === 'DELETE' ? `${base}/keys/${keyId}` : null;
  }
  return null;
}

/** The fields each write may carry; anything else is dropped before it reaches REST. */
const WRITE_FIELDS: Readonly<Record<'catalog-agents' | 'catalog-models', readonly string[]>> = {
  'catalog-agents': ['slug', 'name', 'description', 'runtime', 'model', 'keyIds', 'status'],
  'catalog-models': ['slug', 'name', 'provider', 'modelName', 'modelVersion', 'hosting', 'dataHandling', 'deprecatedAt'],
};

/**
 * The body a proxy forwards: only the collection's fields, as strings, `null`, or (keyIds) strings.
 *
 * @param collection - `catalog-agents` or `catalog-models`.
 * @param raw - The parsed request body.
 */
export function catalogAgentProxyBody(collection: 'catalog-agents' | 'catalog-models', raw: unknown): Record<string, unknown> {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const body: Record<string, unknown> = {};
  for (const field of WRITE_FIELDS[collection]) {
    if (!(field in source)) continue;
    const value = source[field];
    if (field === 'keyIds') {
      if (Array.isArray(value)) body.keyIds = value.filter((v): v is string => typeof v === 'string' && UUID.test(v)).slice(0, 50);
    } else if (value === null || (typeof value === 'string' && value.length <= 4000)) {
      body[field] = value;
    }
  }
  return body;
}
