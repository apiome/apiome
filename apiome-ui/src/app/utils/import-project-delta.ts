/**
 * Import a new version: the Changes step's data (IXH-3.7, #6321).
 *
 * When the Import wizard's slug resolves to an existing Project, the commit lands the spec as a new
 * version on top of that project's latest one. REST `POST /v1/tenants/{tenant}/import/project-delta`
 * (proxied by `POST /api/import/project-delta`) answers what that new version would change: the
 * compatibility engine's verdict (the same rules as Versions → Compare), summary counts, a ranked
 * change list, and both documents for the side-by-side view. A first-time import — or one that lands
 * in the Catalog — answers `204`, and the step is skipped.
 *
 * Everything below the fetch is pure so `import-project-delta.test.ts` can pin it.
 */

/** A change's verb. */
export type ProjectDeltaChangeKind = 'added' | 'changed' | 'removed';

/** A compatibility grade; `null` on a change is "ungraded", which is never read as safe. */
export type ProjectDeltaSeverity = 'breaking' | 'unknown' | 'safe';

/** One structural change (REST `ProjectDeltaChange`). */
export interface ProjectDeltaChange {
  kind: ProjectDeltaChangeKind;
  /** document / path / operation / component / schema. */
  scope: string;
  /** Stable group key, e.g. `DELETE /refunds/{id}`. */
  entity: string;
  /** e.g. `schema Refund.amount minimum`. */
  label: string;
  /** RFC 6901 pointer into the documents. */
  pointer: string;
  /** Scalar old value, or a `{n keys}` / `[n items]` preview. */
  before: unknown;
  /** Scalar new value, or a `{n keys}` / `[n items]` preview. */
  after: unknown;
  severity: ProjectDeltaSeverity | null;
  rules: string[];
  message: string | null;
}

/** The summary bar's numbers (REST `ProjectDeltaCounts`). */
export interface ProjectDeltaCounts {
  added: number;
  changed: number;
  removed: number;
  /** Breaking compatibility findings — the Versions → Compare / gate count. */
  breaking: number;
  /** Every structural change, before any server-side truncation. */
  total: number;
}

/** The Changes step's payload (REST `ProjectDeltaResponse`). */
export interface ProjectDelta {
  project_id: string;
  project_slug: string;
  project_name: string;
  base_revision_id: string;
  base_version_label: string;
  /** Every live version label of the project, oldest first (#590); absent from older servers. */
  existing_version_labels?: string[];
  overall: ProjectDeltaSeverity;
  counts: ProjectDeltaCounts;
  changes: ProjectDeltaChange[];
  truncated: boolean;
  base_document: Record<string, unknown> | null;
  incoming_document: Record<string, unknown> | null;
}

/** What the wizard sends. */
export interface ProjectDeltaRequest {
  /** The analyzed (OpenAPI 3.1) document. */
  document: unknown;
  /** The slug the commit would use. */
  project_slug: string;
}

/**
 * Where the Changes step stands.
 *
 * - `idle` — not asked yet;
 * - `checking` — the request is in flight;
 * - `skip` — not a new version of an existing Project (REST `204`): no Changes step;
 * - `ready` — a delta to show;
 * - `error` — the delta could not be computed; the step shows a retry and never blocks the import.
 */
export type ProjectDeltaState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'skip' }
  | { status: 'ready'; delta: ProjectDelta }
  | { status: 'error'; message: string };

/**
 * Ask whether this import is a new version, and what it changes.
 *
 * @param body The incoming document and the slug the commit would use.
 * @param fetchImpl Injectable for tests.
 * @returns `skip` for a first-time / catalog import, `ready` with the delta, or `error` with a
 *   message — this never throws, because a failed comparison must never block the import.
 */
export async function fetchProjectDelta(
  body: ProjectDeltaRequest,
  fetchImpl: typeof fetch = fetch,
): Promise<ProjectDeltaState> {
  try {
    const res = await fetchImpl('/api/import/project-delta', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => null)) as
      | { success?: boolean; delta?: ProjectDelta | null; error?: string }
      | null;
    if (!res.ok || !data?.success) {
      return {
        status: 'error',
        message: data?.error || 'The latest version could not be compared with this specification.',
      };
    }
    return data.delta ? { status: 'ready', delta: data.delta } : { status: 'skip' };
  } catch (err) {
    return {
      status: 'error',
      message: err instanceof Error && err.message ? err.message : 'The comparison request failed.',
    };
  }
}

/** The change-list filter. */
export type ProjectDeltaFilter = 'all' | 'breaking' | ProjectDeltaChangeKind;

/** Filter options in display order, with their labels. */
export const PROJECT_DELTA_FILTERS: ReadonlyArray<{ value: ProjectDeltaFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'breaking', label: 'Breaking' },
  { value: 'added', label: 'Added' },
  { value: 'changed', label: 'Changed' },
  { value: 'removed', label: 'Removed' },
];

/**
 * The rows a filter keeps, in the server's ranked order (breaking first).
 *
 * @param changes The delta's change list.
 * @param filter The active filter.
 * @param query Free text matched case-insensitively against the label and the pointer.
 * @returns The matching rows.
 */
export function filterProjectDeltaChanges(
  changes: ReadonlyArray<ProjectDeltaChange>,
  filter: ProjectDeltaFilter,
  query = '',
): ProjectDeltaChange[] {
  const needle = query.trim().toLowerCase();
  return changes.filter((c) => {
    if (filter === 'breaking' && c.severity !== 'breaking') return false;
    if (filter !== 'all' && filter !== 'breaking' && c.kind !== filter) return false;
    if (!needle) return true;
    return c.label.toLowerCase().includes(needle) || c.pointer.toLowerCase().includes(needle);
  });
}

/** How many rows the list mounts per page; "Show more" adds another page. */
export const PROJECT_DELTA_PAGE_SIZE = 50;

/** The symbol each kind leads with — never colour alone. */
export const PROJECT_DELTA_KIND_SYMBOL: Readonly<Record<ProjectDeltaChangeKind, string>> = {
  added: '+',
  changed: '~',
  removed: '−',
};

/** The upper-case verb each kind is labelled with in the list. */
export const PROJECT_DELTA_KIND_LABEL: Readonly<Record<ProjectDeltaChangeKind, string>> = {
  added: 'Added',
  changed: 'Changed',
  removed: 'Removed',
};

/**
 * A before/after value as the list prints it.
 *
 * @param value A scalar, `null`, or the server's container preview string.
 * @returns Strings quoted, everything else JSON-ish; `—` for none.
 */
export function formatDeltaValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return /^[{[]\d+ (keys?|items?)[}\]]$/.test(value) ? value : JSON.stringify(value);
  return String(value);
}

/**
 * A one-line `before → after` for a changed scalar, or `null` where it says nothing useful.
 *
 * @param change One row.
 * @returns e.g. `0 → 0.01`, or `null` for an addition or removal.
 */
export function describeDeltaValues(change: ProjectDeltaChange): string | null {
  if (change.kind !== 'changed') return null;
  return `${formatDeltaValue(change.before)} → ${formatDeltaValue(change.after)}`;
}

/**
 * Pretty-print a document for the Monaco diff.
 *
 * @param doc Either side's document.
 * @returns Two-space JSON, or an empty string when the side is missing.
 */
export function prettyDeltaDocument(doc: unknown): string {
  return doc ? JSON.stringify(doc, null, 2) : '';
}
