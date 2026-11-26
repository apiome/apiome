/**
 * Browser calls for the **Pacticipants** pages (PFX-5.1, #6945), through `/api/pact/*`.
 *
 * Every call throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", not "something went wrong"). List bodies are normalised: their arrays are always arrays.
 */

import type {
  LabelPage,
  Pacticipant,
  PacticipantBranchPage,
  PacticipantEnvironmentsResponse,
  PacticipantPage,
  PacticipantVersionPage,
} from '@lib/pact-pacticipants';

/** Where the proxies live. */
const BASE = '/api/pact';

/**
 * Read a proxy response, or throw REST's message.
 *
 * @param response - The proxy's answer.
 * @param fallback - What to say when the failure carried no message.
 * @returns The parsed body.
 */
export async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as unknown;
  if (!response.ok) {
    const error = body && typeof body === 'object' ? (body as Record<string, unknown>).error : undefined;
    throw new Error(typeof error === 'string' && error ? error : fallback);
  }
  return body as T;
}

/**
 * `?a=1&b=2` from the defined, non-empty entries, or an empty string.
 *
 * @param params - The parameters.
 * @returns The query string, with its `?`.
 */
function queryString(params: Record<string, string | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  const rendered = query.toString();
  return rendered ? `?${rendered}` : '';
}

/** A pacticipant's path below `/api/pact`. */
function pacticipantBase(slug: string): string {
  return `${BASE}/pacticipants/${encodeURIComponent(slug)}`;
}

/**
 * One page of the workspace's pacticipants.
 *
 * @param options - `label` narrows the list; `cursor` is the previous page's `next_cursor`.
 * @returns The page.
 */
export async function fetchPacticipants(options: { label?: string | null; cursor?: string | null } = {}) {
  const body = await readJson<PacticipantPage>(
    await fetch(`${BASE}/pacticipants${queryString(options)}`, { cache: 'no-store' }),
    'Could not load the pacticipants',
  );
  return { ...body, pacticipants: Array.isArray(body.pacticipants) ? body.pacticipants : [] };
}

/**
 * The workspace's labels, by name (the first 100).
 *
 * @returns The names.
 */
export async function fetchLabels(): Promise<string[]> {
  const body = await readJson<LabelPage>(
    await fetch(`${BASE}/labels`, { cache: 'no-store' }),
    'Could not load the labels',
  );
  return Array.isArray(body.labels) ? body.labels.map((label) => label.name) : [];
}

/**
 * One pacticipant.
 *
 * @param slug - Its handle.
 * @returns The pacticipant; `labels` is always an array.
 */
export async function fetchPacticipant(slug: string): Promise<Pacticipant> {
  const body = await readJson<Pacticipant>(
    await fetch(pacticipantBase(slug), { cache: 'no-store' }),
    'Could not load the pacticipant',
  );
  return { ...body, labels: Array.isArray(body.labels) ? body.labels : [] };
}

/**
 * One page of a pacticipant's versions, latest recorded first.
 *
 * @param slug - Its handle.
 * @param options - At most one of `branch` / `tag`, and the previous page's `cursor`.
 * @returns The page.
 */
export async function fetchVersions(
  slug: string,
  options: { branch?: string | null; tag?: string | null; cursor?: string | null } = {},
) {
  const body = await readJson<PacticipantVersionPage>(
    await fetch(`${pacticipantBase(slug)}/versions${queryString(options)}`, { cache: 'no-store' }),
    'Could not load the versions',
  );
  return { ...body, versions: Array.isArray(body.versions) ? body.versions : [] };
}

/**
 * One page of a pacticipant's branches, by name.
 *
 * @param slug - Its handle.
 * @param cursor - The previous page's `next_cursor`.
 * @returns The page.
 */
export async function fetchBranches(slug: string, cursor?: string | null) {
  const body = await readJson<PacticipantBranchPage>(
    await fetch(`${pacticipantBase(slug)}/branches${queryString({ cursor })}`, { cache: 'no-store' }),
    'Could not load the branches',
  );
  return { ...body, branches: Array.isArray(body.branches) ? body.branches : [] };
}

/**
 * Every environment, with what the pacticipant runs in it.
 *
 * @param slug - Its handle.
 * @returns The roll-up.
 */
export async function fetchEnvironments(slug: string): Promise<PacticipantEnvironmentsResponse> {
  const body = await readJson<PacticipantEnvironmentsResponse>(
    await fetch(`${pacticipantBase(slug)}/environments`, { cache: 'no-store' }),
    'Could not load the environments',
  );
  return { environments: Array.isArray(body.environments) ? body.environments : [] };
}
