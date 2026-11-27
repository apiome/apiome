/**
 * Browser calls for the **Pacticipants** pages (PFX-5.1, #6945), through `/api/pact/*`.
 *
 * Every read throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", not "something went wrong"). List bodies are normalised: their arrays are always arrays.
 *
 * The writes of PFX-8.10 (#7307) — save settings, add or remove a label, register, delete and
 * restore — answer the result or a {@link WriteFailure} with REST's status, so the screen can put a
 * taken name (409) under the Name field and say anything else where it happened. PFX-8.11 (#7308)
 * adds a version's tag, delete and restore, the deleted versions, and the badge preview.
 */

import type { DeletionImpact, PacticipantCreateBody, PacticipantPatchBody } from '@lib/pact-pacticipant-settings';
import type {
  LabelPage,
  Pacticipant,
  PacticipantBranchPage,
  PacticipantEnvironmentsResponse,
  PacticipantPage,
  PacticipantVersion,
  PacticipantVersionPage,
} from '@lib/pact-pacticipants';
import { tagPathSegment, type DeletedVersion } from '@lib/pact-pacticipant-versions';
import type { BadgeAnswer, BadgeTarget } from '@lib/pact-badges';

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
 * @param options - `label` narrows the list; `state: 'deleted'` lists the deleted ones that can still
 *   be restored; `cursor` is the previous page's `next_cursor`.
 * @returns The page.
 */
export async function fetchPacticipants(
  options: { label?: string | null; cursor?: string | null; state?: 'deleted' | null } = {},
) {
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

/** A refused or failed write: REST's message and status (503 when it could not be reached). */
export interface WriteFailure {
  error: string;
  status: number;
}

/**
 * Send one write through a proxy and read its answer.
 *
 * @param url - The proxy URL.
 * @param method - The method.
 * @param fallback - What to say when the failure carried no message.
 * @param body - The JSON body, if any.
 * @returns The parsed body, or the failure.
 */
async function write<T>(url: string, method: string, fallback: string, body?: unknown): Promise<T | WriteFailure> {
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    });
  } catch {
    return { error: 'The Pact Broker could not be reached. Try again shortly.', status: 503 };
  }
  const parsed = (await response.json().catch(() => ({}))) as unknown;
  if (!response.ok) {
    const error = parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>).error : undefined;
    return { error: typeof error === 'string' && error ? error : fallback, status: response.status };
  }
  return parsed as T;
}

/** `labels` always an array, `aliases` too. */
function normalised(pacticipant: Pacticipant): Pacticipant {
  return {
    ...pacticipant,
    labels: Array.isArray(pacticipant.labels) ? pacticipant.labels : [],
    aliases: Array.isArray(pacticipant.aliases) ? pacticipant.aliases : [],
  };
}

/**
 * Save the fields of the Settings tab that changed (PATCH).
 *
 * @param slug - The pacticipant's handle.
 * @param patch - Only the changed fields; `null` clears one.
 * @returns The pacticipant as stored now, or the failure (409: the name is taken).
 */
export async function savePacticipant(slug: string, patch: PacticipantPatchBody): Promise<Pacticipant | WriteFailure> {
  const answer = await write<Pacticipant>(pacticipantBase(slug), 'PATCH', 'Could not save the settings', patch);
  return 'error' in answer ? answer : normalised(answer);
}

/**
 * Add a label (adding it again changes nothing) or remove one.
 *
 * @param slug - The pacticipant's handle.
 * @param label - The label.
 * @param action - `add` or `remove`.
 * @returns `{}` on success, or the failure.
 */
export async function changeLabel(
  slug: string,
  label: string,
  action: 'add' | 'remove',
): Promise<Record<string, never> | WriteFailure> {
  const answer = await write<unknown>(
    `${pacticipantBase(slug)}/labels/${encodeURIComponent(label)}`,
    action === 'add' ? 'PUT' : 'DELETE',
    action === 'add' ? `Could not add the label ${label}` : `Could not remove the label ${label}`,
  );
  return answer && typeof answer === 'object' && 'error' in answer ? (answer as WriteFailure) : {};
}

/**
 * Register a pacticipant (the New pacticipant dialog).
 *
 * @param body - Its name and optional fields.
 * @returns The stored pacticipant, or the failure (409: the name is taken).
 */
export async function createPacticipant(body: PacticipantCreateBody): Promise<Pacticipant | WriteFailure> {
  const answer = await write<Pacticipant>(`${BASE}/pacticipants`, 'POST', 'Could not create the pacticipant', body);
  return 'error' in answer ? answer : normalised(answer);
}

/**
 * What deleting a pacticipant takes with it.
 *
 * @param slug - Its handle.
 * @returns The impact, or the failure.
 */
export async function fetchDeletionImpact(slug: string): Promise<DeletionImpact | WriteFailure> {
  return write<DeletionImpact>(`${pacticipantBase(slug)}/deletion-impact`, 'GET', 'Could not read what the delete removes');
}

/**
 * Delete a pacticipant with its history (soft: it can be restored for the grace period).
 *
 * @param slug - Its handle.
 * @param reason - Why, stored and audited; empty for none.
 * @returns `{}` on success, or the failure (409: a version is deployed or released).
 */
export async function deletePacticipant(slug: string, reason: string): Promise<Record<string, never> | WriteFailure> {
  const query = reason.trim() ? `?reason=${encodeURIComponent(reason.trim())}` : '';
  const answer = await write<unknown>(`${pacticipantBase(slug)}${query}`, 'DELETE', 'Could not delete the pacticipant');
  return answer && typeof answer === 'object' && 'error' in answer ? (answer as WriteFailure) : {};
}

/**
 * Undo a pacticipant's delete.
 *
 * @param ref - The deleted pacticipant's handle or id (an id chooses among several of one handle).
 * @returns The live pacticipant, or the failure (409: a live pacticipant took the handle since).
 */
export async function restorePacticipant(ref: string): Promise<Pacticipant | WriteFailure> {
  const answer = await write<Pacticipant>(`${pacticipantBase(ref)}/restore`, 'POST', 'Could not restore the pacticipant');
  return 'error' in answer ? answer : normalised(answer);
}

// --- Version management and badges (PFX-8.11, #7308) ------------------------------------------

/** A version's path below `/api/pact`. */
function versionBase(slug: string, number: string): string {
  return `${pacticipantBase(slug)}/versions/${encodeURIComponent(number)}`;
}

/**
 * One page of a pacticipant's deleted versions, still restorable, latest recorded first.
 *
 * @param slug - Its handle.
 * @param cursor - The previous page's `next_cursor`.
 * @returns The page; each version carries `deleted_at`, `delete_cause` and `purge_after`.
 */
export async function fetchDeletedVersions(slug: string, cursor?: string | null) {
  const body = await readJson<{ versions: DeletedVersion[]; has_more: boolean; next_cursor?: string | null }>(
    await fetch(`${pacticipantBase(slug)}/versions${queryString({ state: 'deleted', cursor })}`, { cache: 'no-store' }),
    'Could not load the deleted versions',
  );
  return { ...body, versions: Array.isArray(body.versions) ? body.versions : [] };
}

/**
 * One version, by number.
 *
 * @param slug - The pacticipant's handle.
 * @param number - The version number, exactly as recorded.
 * @returns The version, or the failure (404: no such live version).
 */
export async function fetchVersion(slug: string, number: string): Promise<PacticipantVersion | WriteFailure> {
  return write<PacticipantVersion>(versionBase(slug, number), 'GET', `Could not read version ${number}`);
}

/**
 * Put a tag on a version (tagging it again changes nothing).
 *
 * @param slug - The pacticipant's handle.
 * @param number - The version number.
 * @param tag - The tag; may contain `/`.
 * @returns The version with its tags, or the failure.
 */
export async function tagVersion(slug: string, number: string, tag: string): Promise<PacticipantVersion | WriteFailure> {
  return write<PacticipantVersion>(
    `${versionBase(slug, number)}/tags/${tagPathSegment(tag)}`,
    'PUT',
    `Could not tag ${number} with ${tag}`,
  );
}

/**
 * Delete a version with its pacts and results (soft: it can be restored until it is purged).
 * Never forced: a deployed version is refused (409).
 *
 * @param slug - The pacticipant's handle.
 * @param number - The version number.
 * @param reason - Why, stored and audited; empty for none.
 * @returns `{}` on success, or the failure.
 */
export async function deleteVersion(
  slug: string,
  number: string,
  reason = '',
): Promise<Record<string, never> | WriteFailure> {
  const why = reason.trim();
  const query = why ? `?reason=${encodeURIComponent(why)}` : '';
  const answer = await write<unknown>(`${versionBase(slug, number)}${query}`, 'DELETE', `Could not delete ${number}`);
  return answer && typeof answer === 'object' && 'error' in answer ? (answer as WriteFailure) : {};
}

/**
 * Undo a version's delete: its pacts, results and deployments come back.
 *
 * @param slug - The pacticipant's handle.
 * @param number - The version number.
 * @returns The live version, or the failure (409: a live version took the number since).
 */
export async function restoreVersion(slug: string, number: string): Promise<PacticipantVersion | WriteFailure> {
  return write<PacticipantVersion>(`${versionBase(slug, number)}/restore`, 'POST', `Could not restore ${number}`);
}

/**
 * The public badge REST serves, read anonymously by the proxy, for the preview.
 *
 * @param project - The linked public project's slug.
 * @param target - What the badge is for.
 * @returns The SVG, its state and the workspace handle, or the failure (404: none is served).
 */
export async function fetchBadge(project: string, target: BadgeTarget): Promise<BadgeAnswer | WriteFailure> {
  const params =
    target.kind === 'pacticipant'
      ? { project, pacticipant: target.slug }
      : { project, provider: target.provider, consumer: target.consumer };
  return write<BadgeAnswer>(`${BASE}/badges${queryString(params)}`, 'GET', 'Could not read the badge');
}
