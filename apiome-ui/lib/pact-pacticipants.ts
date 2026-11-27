/**
 * Pacticipants in the UI — PFX-5.1 (#6945).
 *
 * The wire shapes of the pacticipant registry (`GET /v1/tenants/{tenant}/pacticipants`, one
 * pacticipant, its versions and branches, the workspace's labels), the roll-up of what each
 * environment runs of one pacticipant (read from the broker's environment lists), and the pure
 * rules the **Pacticipants** list and detail pages draw them with.
 *
 * The browser only ever reaches REST through the `/api/pact/*` proxies. Those proxies forward the
 * query parameters named here and nothing else: an unknown or oversized parameter is refused with
 * the reason (see {@link pickListQuery}), never dropped.
 */

/** A pacticipant, as `GET …/pacticipants` and `GET …/pacticipants/{ref}` return it. */
export interface Pacticipant {
  id: string;
  slug: string;
  /** The name pacts use. */
  name: string;
  /** What people read, when it differs from `name` (PFX-8.10). */
  display_name?: string | null;
  /** Names it had before it was renamed, oldest first; each still resolves to it (PFX-8.10). */
  aliases?: string[];
  repository_url?: string | null;
  main_branch?: string | null;
  project_id?: string | null;
  consumer_id?: string | null;
  labels: string[];
  created_at?: string | null;
  updated_at?: string | null;
  /** When it was deleted; set only in the `state=deleted` list (PFX-1.11). */
  deleted_at?: string | null;
  /** Who deleted it. */
  deleted_by_label?: string | null;
  /** Why, as the deleter said. */
  delete_reason?: string | null;
  /** When a deleted pacticipant is purged unless it is restored first. */
  purge_after?: string | null;
}

/** One page of pacticipants. */
export interface PacticipantPage {
  pacticipants: Pacticipant[];
  count: number;
  has_more: boolean;
  next_cursor?: string | null;
}

/** One recorded version of a pacticipant. */
export interface PacticipantVersion {
  id: string;
  pacticipant_id: string;
  number: string;
  seq: number;
  build_url?: string | null;
  branches: string[];
  tags: string[];
  actor_label?: string | null;
  created_at?: string | null;
}

/** One page of versions, latest recorded first. */
export interface PacticipantVersionPage {
  versions: PacticipantVersion[];
  count: number;
  has_more: boolean;
  next_cursor?: string | null;
}

/** One branch of a pacticipant, with its head version. */
export interface PacticipantBranch {
  id: string;
  pacticipant_id: string;
  name: string;
  head_version_id: string;
  head_version: string;
  is_main: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

/** One page of branches, by name. */
export interface PacticipantBranchPage {
  branches: PacticipantBranch[];
  count: number;
  has_more: boolean;
  next_cursor?: string | null;
}

/** One page of the workspace's distinct labels. */
export interface LabelPage {
  labels: { name: string }[];
  count: number;
  has_more: boolean;
  next_cursor?: string | null;
}

/** A version of the pacticipant that is deployed to an environment now. */
export interface EnvironmentDeployment {
  version: string;
  /** The application instance it runs as; `null` for the unnamed instance. */
  applicationInstance: string | null;
  deployedAt: string | null;
}

/** A version of the pacticipant that is released, and still supported, in an environment. */
export interface EnvironmentRelease {
  version: string;
  releasedAt: string | null;
}

/** One environment, with what the pacticipant runs there. */
export interface PacticipantEnvironment {
  uuid: string;
  name: string;
  displayName: string;
  production: boolean;
  deployed: EnvironmentDeployment[];
  released: EnvironmentRelease[];
  /** Why this environment's lists could not be read; absent when they were. */
  error?: string;
}

/** What `GET /api/pact/pacticipants/{slug}/environments` answers. */
export interface PacticipantEnvironmentsResponse {
  environments: PacticipantEnvironment[];
}

/** Page size of the pacticipant list and the version list. */
export const PAGE_LIMIT = 50;

/** Page size of the branch list and of the label picker (REST's maximum is 200). */
export const LONG_PAGE_LIMIT = 100;

/** The longest label, branch or tag REST accepts in a filter. */
export const MAX_FILTER_LENGTH = 255;

/** The longest cursor REST accepts. */
export const MAX_CURSOR_LENGTH = 2048;

/** A pacticipant handle (lowercase kebab, the REST handle rule). */
const HANDLE = /^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$/;

/**
 * Whether a value is a well-formed pacticipant handle.
 *
 * @param value - The candidate, e.g. a route segment.
 * @returns True for a handle REST could have issued.
 */
export function isPacticipantHandle(value: string): boolean {
  return HANDLE.test(value);
}

/** The query parameters a list proxy forwards, or why the request is refused. */
export type PickedQuery = { ok: true; query: URLSearchParams } | { ok: false; error: string };

/**
 * Keep the query parameters a list proxy may forward — and refuse the request when it carries
 * anything else, so a parameter is never silently ignored.
 *
 * @param params - The browser's query string.
 * @param allowed - The filter names this list accepts besides `cursor` (e.g. `['label']`).
 * @returns The parameters to forward, or the reason for a 400.
 */
export function pickListQuery(params: URLSearchParams, allowed: readonly string[]): PickedQuery {
  const query = new URLSearchParams();
  for (const [key, raw] of params.entries()) {
    if (query.has(key)) return { ok: false, error: `The ${key} parameter is given more than once.` };
    const value = raw.trim();
    if (key === 'cursor') {
      if (!value || value.length > MAX_CURSOR_LENGTH) return { ok: false, error: 'The cursor is not valid.' };
      query.set(key, value);
      continue;
    }
    if (!allowed.includes(key)) {
      const accepted = [...allowed, 'cursor'].join(', ');
      return { ok: false, error: `Unsupported parameter ${key}: this list accepts ${accepted}.` };
    }
    if (!value) return { ok: false, error: `The ${key} filter is empty.` };
    if (value.length > MAX_FILTER_LENGTH) {
      return { ok: false, error: `The ${key} filter is longer than ${MAX_FILTER_LENGTH} characters.` };
    }
    query.set(key, value);
  }
  return { ok: true, query };
}

/**
 * Append a page size to picked parameters and render them as a REST path.
 *
 * @param path - The path below `/v1/tenants/{slug}`.
 * @param query - The picked parameters.
 * @param limit - The page size.
 * @returns E.g. `pacticipants?limit=50&label=tier-1`.
 */
export function withQuery(path: string, query: URLSearchParams, limit: number): string {
  const all = new URLSearchParams({ limit: String(limit) });
  query.forEach((value, key) => all.set(key, value));
  return `${path}?${all.toString()}`;
}

/** The filters the pacticipant list accepts. */
export const LIST_FILTERS = ['label', 'state'] as const;

/** The filters the version list accepts. */
export const VERSION_FILTERS = ['branch', 'tag'] as const;

/** The REST path of one pacticipant, or `null` for a malformed handle. */
export function pacticipantProxyPath(slug: string): string | null {
  return isPacticipantHandle(slug) ? `pacticipants/${slug}` : null;
}

/** The REST path of the workspace's labels (the first {@link LONG_PAGE_LIMIT}). */
export const LABELS_PROXY_PATH = `pacticipant-labels?limit=${LONG_PAGE_LIMIT}`;

/** The REST path of the workspace's environments (the broker surface; not paged). */
export const ENVIRONMENTS_PROXY_PATH = 'pact-broker/environments';

/** The route of the pacticipant list. */
export const PACTICIPANTS_ROUTE = '/ade/dashboard/pacts/pacticipants';

/**
 * The route of one pacticipant's page.
 *
 * @param slug - Its handle.
 * @returns E.g. `/ade/dashboard/pacts/pacticipants/billing-service`.
 */
export function pacticipantRoute(slug: string): string {
  return `${PACTICIPANTS_ROUTE}/${encodeURIComponent(slug)}`;
}

/** The CLI snippet an empty workspace shows: publishing a pact registers both pacticipants. */
export const PUBLISH_SNIPPET = [
  'apiome pact publish ./pacts \\',
  '  --consumer-app-version "$GIT_COMMIT" \\',
  '  --branch "$GIT_BRANCH"',
].join('\n');

/** The CLI snippet an empty environments section shows. */
export function recordDeploymentSnippet(name: string): string {
  return `apiome pact record-deployment --pacticipant "${name}" --version "$GIT_COMMIT" --environment production`;
}

/**
 * When something happened, as the tables print it: `2026-11-24 14:05 UTC`, or an em dash.
 *
 * UTC on purpose — the same row reads the same for every viewer and in every screenshot.
 *
 * @param iso - An ISO-8601 timestamp.
 * @returns The short form.
 */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

/**
 * A version number as a table prints it: a 40-character commit SHA is cut to 12, anything else is
 * kept whole. The full number stays in the cell's `title`.
 *
 * @param number - The version number.
 * @returns The short form.
 */
export function shortVersion(number: string): string {
  return /^[0-9a-f]{40}$/i.test(number) ? number.slice(0, 12) : number;
}

/**
 * The repository URL to link to, or `null` when it is not an http(s) URL — a stored value is
 * never turned into a `javascript:` link.
 *
 * @param url - The stored repository URL.
 * @returns The URL, or `null`.
 */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : null;
  } catch {
    return null;
  }
}

/**
 * The sentence above the version table: how many are shown and what narrows them.
 *
 * @param count - Rows loaded so far.
 * @param hasMore - Whether REST has more.
 * @param filter - The branch / tag filter in force.
 * @returns E.g. `50+ versions on branch main, tagged prod`.
 */
export function versionsSummary(
  count: number,
  hasMore: boolean,
  filter: { branch?: string | null; tag?: string | null },
): string {
  const shown = `${count}${hasMore ? '+' : ''} ${count === 1 && !hasMore ? 'version' : 'versions'}`;
  const narrowed = [
    filter.branch ? `on branch ${filter.branch}` : null,
    filter.tag ? `tagged ${filter.tag}` : null,
  ].filter(Boolean);
  return narrowed.length > 0 ? `${shown} ${narrowed.join(', ')}` : shown;
}

// --- the environment roll-up ------------------------------------------------------------------

/** One REST read: its status and parsed body. */
export interface RestRead {
  ok: boolean;
  status: number;
  body: unknown;
}

/** How the roll-up reads a path below `/v1/tenants/{slug}`. */
export type RestReader = (path: string) => Promise<RestRead>;

/** How many environments are read at the same time. */
export const ENVIRONMENT_READ_BATCH = 4;

/** A refusal of the roll-up: REST's status and message. */
export class RollupError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'RollupError';
  }
}

/** A plain object, or an empty one. */
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/** A string field, or `null`. */
function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** `_embedded[key]` as an array of objects. */
function embedded(body: unknown, key: string): Record<string, unknown>[] {
  const list = record(record(body)._embedded)[key];
  return Array.isArray(list) ? list.map(record) : [];
}

/** REST's message from a failed read, or the fallback. */
function failureMessage(read: RestRead, fallback: string): string {
  const detail = record(read.body).detail;
  if (typeof detail === 'string' && detail) return detail;
  const message = text(record(detail).message);
  return message || fallback;
}

/**
 * Read one environment's deployments and supported releases of the pacticipant.
 *
 * A failed read is reported on the environment (its `error`), never dropped.
 *
 * @param read - The REST reader.
 * @param slug - The pacticipant's handle.
 * @param environment - The environment, as the list returned it.
 * @returns The environment with its two lists.
 */
async function readEnvironment(
  read: RestReader,
  slug: string,
  environment: Record<string, unknown>,
): Promise<PacticipantEnvironment> {
  const uuid = text(environment.uuid) ?? '';
  const name = text(environment.name) ?? uuid;
  const base: PacticipantEnvironment = {
    uuid,
    name,
    displayName: text(environment.displayName) ?? name,
    production: environment.production === true,
    deployed: [],
    released: [],
  };
  const query = `?pacticipant=${encodeURIComponent(slug)}`;
  const root = `${ENVIRONMENTS_PROXY_PATH}/${encodeURIComponent(uuid)}`;
  const [deployed, released] = await Promise.all([
    read(`${root}/deployed-versions/currently-deployed${query}`),
    read(`${root}/released-versions/currently-supported${query}`),
  ]);
  const problems: string[] = [];
  if (deployed.ok) {
    base.deployed = embedded(deployed.body, 'deployedVersions').map((row) => ({
      version: text(record(record(row._embedded).version).number) ?? '',
      applicationInstance: text(row.applicationInstance),
      deployedAt: text(row.createdAt),
    }));
  } else {
    problems.push(`Deployments: ${failureMessage(deployed, `HTTP ${deployed.status}`)}`);
  }
  if (released.ok) {
    base.released = embedded(released.body, 'releasedVersions').map((row) => ({
      version: text(record(record(row._embedded).version).number) ?? '',
      releasedAt: text(row.createdAt),
    }));
  } else {
    problems.push(`Releases: ${failureMessage(released, `HTTP ${released.status}`)}`);
  }
  if (problems.length > 0) base.error = problems.join(' ');
  return base;
}

/**
 * Every environment of the workspace, with what one pacticipant runs in it — deployed versions
 * and supported releases. Environments are read {@link ENVIRONMENT_READ_BATCH} at a time.
 *
 * @param read - Reads a path below `/v1/tenants/{slug}` as the signed-in user.
 * @param slug - The pacticipant's handle.
 * @returns The environments, in REST's order (by name).
 * @throws RollupError when the environment list itself cannot be read (REST's status kept).
 */
export async function collectPacticipantEnvironments(
  read: RestReader,
  slug: string,
): Promise<PacticipantEnvironmentsResponse> {
  const list = await read(ENVIRONMENTS_PROXY_PATH);
  if (!list.ok) {
    throw new RollupError(list.status, failureMessage(list, 'The environments could not be read.'));
  }
  const rows = embedded(list.body, 'environments');
  const environments: PacticipantEnvironment[] = [];
  for (let start = 0; start < rows.length; start += ENVIRONMENT_READ_BATCH) {
    const batch = rows.slice(start, start + ENVIRONMENT_READ_BATCH);
    environments.push(...(await Promise.all(batch.map((row) => readEnvironment(read, slug, row)))));
  }
  return { environments };
}
