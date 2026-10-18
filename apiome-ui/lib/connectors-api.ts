/**
 * Browser-side shapes and calls for the Connectors pages (CDG-1.7, #5958).
 *
 * Every call goes through the `/api/connectors/*` and `/api/refresh-runs` proxies (auth and
 * forwarding only — permissions are REST's `imports` resource). A failure throws
 * {@link ConnectorApiError} carrying REST's message and status, so a page can show the provider's
 * reason (a failing dry run) rather than a generic error.
 */

/** A connector, as `GET /connectors` describes it (never a credential). */
export interface Connector {
  id: string;
  kind: string;
  name: string;
  baseUrl: string | null;
  scope: Record<string, unknown>;
  refreshIntervalSeconds: number | null;
  conflictPolicy: string;
  status: 'active' | 'paused' | 'failing' | string;
  hasCredentials: boolean;
  syncable: boolean;
  lastRunAt: string | null;
  createdAt: string | null;
}

/** `GET /connectors`. */
export interface ConnectorList {
  connectors: Connector[];
  kinds: string[];
  syncableKinds: string[];
}

/** One API in a connector's inventory. */
export interface ConnectorItem {
  id: string;
  remoteId: string;
  remoteName: string | null;
  environment: string | null;
  hosts: string[];
  basePath: string | null;
  remoteRevision: string | null;
  status: string;
  catalogItemId: string | null;
  lastSeenAt: string | null;
  ignoredReason?: string | null;
}

/** One row of the refresh ledger: a Git refresh job or a connector run. */
export interface RefreshRun {
  id: string;
  source: 'git' | 'connector' | string;
  status: string;
  reason: string | null;
  trigger: string | null;
  connectorId: string | null;
  connectorName: string | null;
  connectorKind: string | null;
  repositoryId: string | null;
  repositoryName: string | null;
  branch: string | null;
  path: string | null;
  errorClass: string | null;
  httpStatus: number | null;
  errorMessage: string | null;
  pullCount: number;
  summary: Record<string, unknown>;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

/** A connector run, as `POST …/sync` returns it. */
export interface ConnectorRun {
  id: string;
  status: string;
  errorClass: string | null;
  httpStatus: number | null;
  errorMessage: string | null;
  summary: Record<string, unknown>;
}

/** The dry run's answer. */
export interface DryRunResult {
  itemCount: number;
  items: { remoteId: string; name: string | null; environment: string | null; revision: string | null }[];
  truncated: boolean;
  findings: Record<string, unknown>[];
}

/** A refused call: REST's message, its HTTP status and, for a refusal, its stable reason. */
export class ConnectorApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = 'ConnectorApiError';
  }
}

async function call<T>(url: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: init?.method ?? 'GET',
      headers: init?.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      cache: 'no-store',
    });
  } catch {
    throw new ConnectorApiError('The connector API did not answer. Check your connection and try again.', 0);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      typeof body?.error === 'string' ? body.error : `The request failed (HTTP ${response.status}). Try again.`;
    throw new ConnectorApiError(message, response.status);
  }
  return body as T;
}

/** The tenant's connectors and the kinds this deployment can sync. */
export function listConnectors(): Promise<ConnectorList> {
  return call<ConnectorList>('/api/connectors');
}

/** One connector. */
export function getConnector(id: string): Promise<Connector> {
  return call<Connector>(`/api/connectors/${encodeURIComponent(id)}`);
}

/** The body of a create or dry run: what the connector is. */
export interface ConnectorDraft {
  kind: string;
  baseUrl?: string | null;
  scope: Record<string, unknown>;
}

/** Ask the provider once what the connector would sync; nothing is stored. */
export function dryRunConnector(draft: ConnectorDraft, credentials: Record<string, string> | null): Promise<DryRunResult> {
  return call<DryRunResult>('/api/connectors/dry-run', {
    method: 'POST',
    body: { ...draft, baseUrl: draft.baseUrl || undefined, credentials: credentials ?? undefined },
  });
}

/** Register a connector, then store its credential when it has one. */
export async function createConnector(
  draft: ConnectorDraft & { name: string; refreshIntervalSeconds: number | null; conflictPolicy: string },
  credentials: Record<string, string> | null
): Promise<Connector> {
  const created = await call<Connector>('/api/connectors', {
    method: 'POST',
    body: {
      kind: draft.kind,
      name: draft.name,
      baseUrl: draft.baseUrl || undefined,
      scope: draft.scope,
      refreshIntervalSeconds: draft.refreshIntervalSeconds ?? undefined,
      conflictPolicy: draft.conflictPolicy,
    },
  });
  if (credentials) await putCredentials(created.id, credentials);
  return created;
}

/** Change a connector's settings. */
export function updateConnector(id: string, changes: Record<string, unknown>): Promise<Connector> {
  return call<Connector>(`/api/connectors/${encodeURIComponent(id)}`, { method: 'PATCH', body: changes });
}

/** Replace a connector's credential as a whole. */
export function putCredentials(id: string, credentials: Record<string, string>): Promise<unknown> {
  return call(`/api/connectors/${encodeURIComponent(id)}/credentials`, { method: 'PUT', body: { credentials } });
}

/** Delete a connector (its catalog items stay). */
export function deleteConnector(id: string): Promise<unknown> {
  return call(`/api/connectors/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** Sync now; resolves with the finished run. */
export function syncConnector(id: string): Promise<ConnectorRun> {
  return call<ConnectorRun>(`/api/connectors/${encodeURIComponent(id)}/sync`, { method: 'POST' });
}

/** A page of a connector's inventory. */
export function listConnectorItems(
  id: string,
  options: { status?: string | null; limit?: number; offset?: number } = {}
): Promise<{ items: ConnectorItem[]; total: number }> {
  const query = new URLSearchParams();
  if (options.status) query.set('status', options.status);
  query.set('limit', String(options.limit ?? 100));
  if (options.offset) query.set('offset', String(options.offset));
  return call(`/api/connectors/${encodeURIComponent(id)}/items?${query.toString()}`);
}

/** A page of the refresh ledger, optionally one connector's. */
export function listRefreshRuns(
  options: { connector?: string | null; source?: string | null; limit?: number; offset?: number } = {}
): Promise<{ runs: RefreshRun[]; total: number }> {
  const query = new URLSearchParams();
  if (options.connector) query.set('connector', options.connector);
  if (options.source) query.set('source', options.source);
  query.set('limit', String(options.limit ?? 25));
  if (options.offset) query.set('offset', String(options.offset));
  return call(`/api/refresh-runs?${query.toString()}`);
}

/**
 * A run's one-line outcome, for the ledger and the sync toast.
 *
 * @param run - A ledger row or a sync answer.
 * @returns For example "Imported 3 of 5", "Unchanged", or the error class and status.
 */
export function runOutcome(run: Pick<RefreshRun, 'status' | 'summary' | 'errorClass' | 'httpStatus' | 'source'>): string {
  if (run.status === 'failed') {
    const status = run.httpStatus ? ` (HTTP ${run.httpStatus})` : '';
    return `Failed: ${run.errorClass ?? 'error'}${status}`;
  }
  if (run.status === 'running' || run.status === 'queued') return 'Running';
  if (run.source === 'git') return run.status === 'succeeded' ? 'Refreshed' : run.status;
  const summary = run.summary ?? {};
  const imported = Number(summary.imported ?? 0);
  const candidates = Number(summary.candidates ?? 0);
  if (imported > 0) return `Imported ${imported} of ${candidates}`;
  return candidates > 0 ? `Unchanged (${candidates} checked)` : 'Nothing to sync';
}
