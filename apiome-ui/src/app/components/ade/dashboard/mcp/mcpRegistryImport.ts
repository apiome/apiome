/**
 * "From a registry" in the Add MCP server dialog — pure helpers (AAU-5.4, #5725).
 *
 * A team that already keeps its MCP inventory in a registry (the official MCP registry, Azure API
 * Center, a Kong MCP registry, or another Apiome workspace's registry endpoint) brings the whole
 * inventory in at once instead of one server at a time. The dialog does it with the existing
 * `mcp-registry` connector (CDG-4.4): it registers one connector for the registry, stores the
 * optional credential (sealed server-side), and runs its first sync, which pages the registry,
 * adds each server with a reachable remote to the MCP catalog, discovers and grades it. Later syncs
 * of the same connector re-import only entries whose digest changed. A registry URL resolving to a
 * private address is refused by the server, and every sync is recorded in the refresh ledger with
 * its counts.
 *
 * This module holds the form, its validation, the connector draft and the run summary — no React,
 * no network — so every rule is unit-tested.
 */

import type { ConnectorRun } from '@lib/connectors-api';

/** The REST connector kind the dialog registers. */
export const MCP_REGISTRY_CONNECTOR_KIND = 'mcp-registry';

/**
 * "Keep these servers in sync" sends no cadence of its own: the server re-syncs an `mcp-registry`
 * connector hourly by default (`APIOME_MCP_REGISTRY_SYNC_INTERVAL`, V2-MCP-26.3). Left unticked, the
 * connector is registered `paused`, so it syncs only when asked.
 */
export const REGISTRY_SYNC_PAUSED = 'paused';

/** The conflict policy every new connector starts with (the Add connector page's default). */
const DEFAULT_CONFLICT_POLICY = 'hold-for-review';

/** How the registry is authenticated. */
export type McpRegistryCredentialType = 'none' | 'token' | 'apiKey';

export const MCP_REGISTRY_CREDENTIAL_OPTIONS: { value: McpRegistryCredentialType; label: string; hint: string }[] = [
  { value: 'none', label: 'None (public registry)', hint: 'The official registry and most public ones need no credential.' },
  { value: 'token', label: 'Bearer token', hint: 'Sent as Authorization: Bearer on every registry request.' },
  {
    value: 'apiKey',
    label: 'Apiome workspace API key',
    hint: "Another Apiome workspace's registry endpoint takes one of its API keys (sent as X-API-Key).",
  },
];

/** The registry half of the Add MCP server form. */
export interface McpRegistryForm {
  /** The registry root, e.g. `https://registry.modelcontextprotocol.io`. */
  registryUrl: string;
  /** Optional name filter (the connector's `search` scope). */
  search: string;
  credentialType: McpRegistryCredentialType;
  /** The token or API key; ignored when `credentialType` is `none`. */
  credential: string;
  /** Keep the connector on the hourly registry sync (otherwise it is paused and syncs only when asked). */
  keepInSync: boolean;
}

/** A fresh registry form. */
export function emptyMcpRegistryForm(): McpRegistryForm {
  return { registryUrl: '', search: '', credentialType: 'none', credential: '', keepInSync: true };
}

/**
 * Validate the registry form before any request.
 *
 * @param form - The form.
 * @returns A human-readable error, or `null` when it can be submitted. Private addresses are
 *   refused by the server, which applies the connector address rule (the browser cannot resolve).
 */
export function validateMcpRegistryForm(form: McpRegistryForm): string | null {
  const url = (form.registryUrl ?? '').trim();
  if (!url) return 'Enter the registry URL.';
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return 'Enter a valid registry URL (including https://).';
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return 'The registry URL must start with http:// or https://.';
  }
  if (form.credentialType !== 'none' && !(form.credential ?? '').trim()) {
    return form.credentialType === 'token' ? 'Enter the bearer token.' : 'Enter the Apiome workspace API key.';
  }
  return null;
}

/** The connector `POST /api/connectors` registers for a registry import. */
export interface McpRegistryConnectorDraft {
  kind: string;
  name: string;
  baseUrl: string;
  scope: Record<string, unknown>;
  refreshIntervalSeconds: number | null;
  conflictPolicy: string;
  /** `paused` when the servers are not kept in sync; omitted otherwise. */
  status?: typeof REGISTRY_SYNC_PAUSED;
}

/**
 * The connector draft for a registry form.
 *
 * @param form - A valid form.
 * @returns `mcp-registry`, named after the registry host (and search, when one narrows it), with the
 *   search scope and no cadence of its own (the server's hourly registry default); `paused` when
 *   "Keep these servers in sync" is off.
 */
export function buildRegistryConnectorDraft(form: McpRegistryForm): McpRegistryConnectorDraft {
  const baseUrl = form.registryUrl.trim();
  const search = form.search.trim();
  let host = baseUrl;
  try {
    host = new URL(baseUrl).host || baseUrl;
  } catch {
    // validated before this is called; keep the raw text as a fallback name
  }
  return {
    kind: MCP_REGISTRY_CONNECTOR_KIND,
    name: `MCP registry · ${host}${search ? ` · ${search}` : ''}`.slice(0, 200),
    baseUrl,
    scope: search ? { search } : {},
    refreshIntervalSeconds: null,
    conflictPolicy: DEFAULT_CONFLICT_POLICY,
    ...(form.keepInSync ? {} : { status: REGISTRY_SYNC_PAUSED }),
  };
}

/**
 * The connector credential for a registry form.
 *
 * @returns `{ token }` / `{ apiKey }`, or `null` for a public registry.
 */
export function buildRegistryCredentials(form: McpRegistryForm): Record<string, string> | null {
  const credential = (form.credential ?? '').trim();
  if (form.credentialType === 'none' || !credential) return null;
  return form.credentialType === 'token' ? { token: credential } : { apiKey: credential };
}

/** One registry entry the import left `discovered`, with why. */
export interface RegistryDiscoveredEntry {
  remoteId: string;
  reason: string;
}

/** What the first sync did, as the result panel shows it. */
export interface RegistryImportSummary {
  /** `succeeded`, `partial`, `failed` … (the run status). */
  status: string;
  /** Entries the registry listed. */
  listed: number;
  /** Servers added (or refreshed) and discovered. */
  imported: number;
  /** Entries kept as `discovered` — no reachable remote, refused or unreachable. */
  discovered: number;
  /** Entries that failed. */
  failed: number;
  discoveredEntries: RegistryDiscoveredEntry[];
  /** The run's error message, when it failed. */
  error: string | null;
}

function count(summary: Record<string, unknown>, key: string): number {
  const value = summary[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/**
 * Read a connector run into the result panel's terms.
 *
 * @param run - `POST /api/connectors/{id}/sync`'s run.
 * @returns The counts and the entries left discovered.
 */
export function summarizeRegistryRun(run: ConnectorRun): RegistryImportSummary {
  const summary = run.summary ?? {};
  const raw = Array.isArray(summary.discoveredItems) ? summary.discoveredItems : [];
  const discoveredEntries = raw
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      remoteId: String(item.remoteId ?? ''),
      reason: String(item.reason ?? item.discoveredReason ?? ''),
    }))
    .filter((item) => item.remoteId);
  return {
    status: run.status,
    listed: count(summary, 'candidates'),
    imported: count(summary, 'imported'),
    discovered: count(summary, 'discovered'),
    failed: count(summary, 'failed'),
    discoveredEntries,
    error: run.errorMessage ?? null,
  };
}

/** Whether a run imported nothing because it failed outright (the registry refused or did not answer). */
export function registryRunFailed(run: ConnectorRun): boolean {
  return run.status === 'failed';
}

/**
 * The first part of a `discoveredReason` — its stable code (`no-remote`, `remote-templated`,
 * `remote-refused`, `remote-unreachable`, and from V2-MCP-26.3 `name-not-namespaced`, `duplicate-name`,
 * `registry-deleted`) — and the explanation after it.
 */
export function splitDiscoveredReason(reason: string): { code: string; detail: string } {
  const index = reason.indexOf(':');
  if (index <= 0) return { code: '', detail: reason };
  return { code: reason.slice(0, index).trim(), detail: reason.slice(index + 1).trim() };
}
