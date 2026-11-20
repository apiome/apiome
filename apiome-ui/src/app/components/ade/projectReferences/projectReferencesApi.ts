/**
 * `$ref` hygiene transport and model — COA-2.8 (#7051).
 *
 * Thin `fetch` wrappers over `/api/projects/{p}/references*` and `/api/external-ref-policy`, which
 * forward to apiome-rest for the session's tenant, plus the pure helpers the **References** tab uses
 * to word statuses, reasons and the policy. Every call resolves with parsed data or throws a
 * {@link ReferencesError} carrying the REST message, status and refusal code.
 */

/** A reference's status. `not-fetched` until its first refresh. */
export type ReferenceStatus = 'not-fetched' | 'ok' | 'changed' | 'unreachable' | 'blocked';

/** The tenant's external-ref policy modes. */
export type ExternalRefMode = 'block' | 'inline' | 'proxy-fetch';

/** One place a reference is used. */
export interface ReferenceLocation {
  /** JSON Pointer of the `$ref` (`#/components/schemas/Money`). */
  location: string;
  /** The reference as written. */
  ref: string;
}

/** One row of a detected change. */
export interface ReferenceChange {
  pointer: string;
  kind: 'added' | 'removed' | 'changed';
  before?: unknown;
  after?: unknown;
}

/** The last change a refresh found. */
export interface ReferenceDiff {
  changes: ReferenceChange[];
  total: number;
  truncated: boolean;
  /** What the new document was compared with. */
  against: 'pin' | 'previous';
  from_digest?: string;
  to_digest?: string;
}

/** One external reference (REST `ProjectReference`). */
export interface ProjectReference {
  url: string;
  host: string;
  locations: ReferenceLocation[];
  status: ReferenceStatus;
  reason: string | null;
  detail: string | null;
  digest: string | null;
  fetched_at: string | null;
  checked_at: string | null;
  pinned: { digest: string; at: string | null } | null;
  diff: ReferenceDiff | null;
}

/** A loop of internal references (REST `RefCycle`). */
export interface ReferenceCycle {
  refs: string[];
  path: string[];
}

/** The external-ref policy in force (REST `ExternalRefPolicyOut`). */
export interface ExternalRefPolicy {
  mode: ExternalRefMode;
  allowlist: string[];
  /** The deployment kill switch. */
  resolution_allowed: boolean;
  /** Whether the policy can fetch anything. */
  fetches: boolean;
  /** Whether the caller is a tenant administrator. */
  can_edit: boolean;
}

/** A version's references (REST `ProjectReferencesOut`). */
export interface ProjectReferences {
  project_id: string;
  version_record_id: string;
  version_label: string | null;
  references: ProjectReference[];
  summary: Partial<Record<ReferenceStatus, number>>;
  cycles: ReferenceCycle[];
  cycle_total: number;
  cycles_truncated: boolean;
  policy: ExternalRefPolicy;
  /** References fetched by this refresh (refresh replies only). */
  refreshed?: number | null;
}

/** A refused or failed call. */
export class ReferencesError extends Error {
  /** The HTTP status (0 when the request never got an answer). */
  readonly status: number;

  /** apiome-rest's refusal code, e.g. `ref-not-fetched`. */
  readonly code: string | null;

  /**
   * @param message What went wrong, fit to show.
   * @param status The HTTP status.
   * @param code The refusal code, when there is one.
   */
  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = 'ReferencesError';
    this.status = status;
    this.code = code;
  }
}

/** Readable status names. */
export const STATUS_LABEL: Record<ReferenceStatus, string> = {
  'not-fetched': 'Not fetched',
  ok: 'Up to date',
  changed: 'Changed',
  unreachable: 'Unreachable',
  blocked: 'Blocked',
};

/** The badge tone of each status. */
export const STATUS_TONE: Record<ReferenceStatus, 'neutral' | 'ok' | 'warn' | 'danger'> = {
  'not-fetched': 'neutral',
  ok: 'ok',
  changed: 'warn',
  unreachable: 'danger',
  blocked: 'danger',
};

/** Readable policy mode names. */
export const MODE_LABEL: Record<ExternalRefMode, string> = {
  block: 'Block',
  inline: 'Fetch',
  'proxy-fetch': 'Fetch allowlisted hosts only',
};

/** Why a fetch was refused or failed, in the product's words (REST reason codes). */
const REASON_TEXT: Record<string, string> = {
  'blocked-by-tenant-policy': "The workspace's external reference policy is Block.",
  'host-not-allowlisted': 'This host is not on the allowlist.',
  'allowlist-empty': 'The policy fetches only allowlisted hosts, and the allowlist is empty.',
  'resolution-disabled': 'Fetching remote references is turned off for this deployment.',
  'unsupported-scheme': 'Only http and https references can be fetched.',
  'invalid-url': 'The reference is not a fetchable URL.',
  'blocked-by-ssrf-guard': 'The address is private or local, so it was not fetched.',
  'fetch-failed': 'The host did not answer, or answered with an error.',
  'unparseable-document': 'The host answered, but not with JSON or YAML.',
};

/**
 * Why a reference is blocked or unreachable.
 *
 * @param reference The reference.
 * @returns A sentence, or null when there is nothing to explain.
 */
export function reasonText(reference: Pick<ProjectReference, 'reason' | 'detail'>): string | null {
  if (!reference.reason) return null;
  return REASON_TEXT[reference.reason] ?? reference.detail ?? reference.reason;
}

/**
 * One line describing the policy.
 *
 * @param policy The policy in force.
 * @returns For example `Fetch allowlisted hosts only: *.acme.com`.
 */
export function policySummary(policy: ExternalRefPolicy): string {
  if (!policy.resolution_allowed) return 'Fetching remote references is turned off for this deployment.';
  const label = MODE_LABEL[policy.mode];
  if (policy.mode === 'block') return `${label}: nothing is fetched.`;
  if (policy.allowlist.length === 0) {
    return policy.mode === 'proxy-fetch'
      ? `${label}: the allowlist is empty, so nothing is fetched.`
      : `${label}: any public host.`;
  }
  return `${label}: ${policy.allowlist.join(', ')}.`;
}

/**
 * Split an allowlist typed one pattern per line (commas also separate).
 *
 * @param text The textarea's value.
 * @returns The patterns, trimmed, without blanks.
 */
export function parseAllowlist(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((pattern) => pattern.trim())
    .filter(Boolean);
}

/**
 * A short form of a digest for a table cell.
 *
 * @param digest A sha-256 hex digest (optionally `sha256:`-prefixed).
 * @returns The first 12 hex digits, or `—`.
 */
export function shortDigest(digest: string | null | undefined): string {
  if (!digest) return '—';
  const hex = digest.includes(':') ? digest.split(':')[1] : digest;
  return hex.slice(0, 12);
}

/**
 * A changed value as one short line (strings unquoted, cut at 120 characters).
 *
 * @param value The value.
 * @param present Whether there is a value at all.
 */
export function formatValue(value: unknown, present: boolean): string {
  if (!present) return '—';
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > 120 ? `${text.slice(0, 119)}…` : text;
}

/**
 * Call one route and unwrap `{success, data}`.
 *
 * @param url The BFF URL.
 * @param init `method` and JSON `body`.
 * @returns The `data` of a successful reply.
 * @throws ReferencesError on a refusal or an unreadable reply.
 */
async function call(url: string, init: { method?: string; body?: unknown } = {}): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: init.method ?? 'GET',
      credentials: 'include',
      headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new ReferencesError('Apiome could not be reached.', 0);
  }
  let payload: { success?: boolean; data?: unknown; error?: unknown; code?: unknown } = {};
  try {
    payload = (await response.json()) as typeof payload;
  } catch {
    payload = {};
  }
  if (payload.success !== true) {
    throw new ReferencesError(
      typeof payload.error === 'string' && payload.error ? payload.error : 'Request failed',
      response.status,
      typeof payload.code === 'string' ? payload.code : null
    );
  }
  return payload.data;
}

/** The BFF base URL of a project's references. */
export function referencesUrl(projectId: string, suffix = ''): string {
  return `/api/projects/${encodeURIComponent(projectId)}/references${suffix}`;
}

/** List a version's references (the latest version when `versionId` is empty). */
export async function fetchProjectReferences(projectId: string, versionId?: string | null): Promise<ProjectReferences> {
  const query = versionId ? `?version=${encodeURIComponent(versionId)}` : '';
  return (await call(`${referencesUrl(projectId)}${query}`)) as ProjectReferences;
}

/** Refresh a version's references (every one, or `urls`). */
export async function refreshProjectReferences(
  projectId: string,
  versionId?: string | null,
  urls?: string[]
): Promise<ProjectReferences> {
  const body: Record<string, unknown> = {};
  if (versionId) body.version = versionId;
  if (urls) body.urls = urls;
  return (await call(referencesUrl(projectId, '/refresh'), { method: 'POST', body })) as ProjectReferences;
}

/** Pin a reference's last fetched snapshot. */
export async function pinProjectReference(projectId: string, url: string): Promise<ProjectReference> {
  return (await call(referencesUrl(projectId, '/pin'), { method: 'PUT', body: { url } })) as ProjectReference;
}

/** Remove a reference's pin. */
export async function unpinProjectReference(projectId: string, url: string): Promise<ProjectReference> {
  return (await call(`${referencesUrl(projectId, '/pin')}?url=${encodeURIComponent(url)}`, {
    method: 'DELETE',
  })) as ProjectReference;
}

/** Change the tenant's external-ref policy (administrators only). */
export async function saveExternalRefPolicy(mode: ExternalRefMode, allowlist: string[]): Promise<ExternalRefPolicy> {
  return (await call('/api/external-ref-policy', { method: 'PUT', body: { mode, allowlist } })) as ExternalRefPolicy;
}

/**
 * A timestamp as `2026-11-20 14:05 UTC` (or `—`).
 *
 * @param value An ISO timestamp, or null.
 */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}
