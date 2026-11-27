/**
 * A pacticipant's **Versions** tab — PFX-8.11 (#7308).
 *
 * The pure rules behind `/ade/dashboard/pacts/pacticipants/{handle}/versions`: the views (filter
 * chips) and what each one reads, the search over the loaded versions, what each environment runs
 * of a version, why a version cannot be deleted, how a bulk action reports what it did, and the
 * **The same, from anywhere** actions (`apiome pact create-version-tag`, `delete-version`,
 * `restore-version`).
 *
 * The browser only reaches REST through the `/api/pact/*` proxies. Every refusal is said, with
 * its reason: a version that is deployed is never deleted with `force`, a search never pretends to
 * cover versions that were not read, and a bulk action names every version it did not change.
 */

import { tenantPath, type PactAction } from '@lib/pact-commands';
import { labelProblem } from '@lib/pact-pacticipant-settings';
import { CAN_I_DEPLOY_ROUTE, MATRIX_ROUTE, matrixQueryParams, type MatrixRow } from '@lib/pact-matrix';
import type { PacticipantEnvironment, PacticipantVersion } from '@lib/pact-pacticipants';

/** The Versions tab's segment below a pacticipant's route. */
export const VERSIONS_SEGMENT = 'versions';

/** Tagging a version needs this permission (REST's `PUT …/tags/{tag}`). */
export const TAG_PERMISSION = 'pacts:create';

/** Deleting and restoring a version need this permission. */
export const DELETE_VERSION_PERMISSION = 'pacts:delete';

/** The longest version number REST stores. */
export const MAX_VERSION_LENGTH = 255;

/** How many versions the Deployed and Unverified views read one by one, at most. */
export const MAX_VIEW_LOOKUPS = 50;

/** How many reads or writes the tab sends at once. */
export const VERSION_BATCH = 4;

/** The matrix rows the Unverified view reads (the broker's maximum). */
export const UNVERIFIED_MATRIX_LIMIT = 1000;

/** The longest reason REST stores with a delete. */
export const MAX_VERSION_REASON_LENGTH = 500;

/** A deleted version, as `GET …/versions?state=deleted` lists it. */
export interface DeletedVersion extends PacticipantVersion {
  deleted_at?: string | null;
  deleted_by_label?: string | null;
  delete_reason?: string | null;
  /** `version` (on its own), `pacticipant` (with its pacticipant) or `retention`. */
  delete_cause?: string | null;
  /** When it is purged unless it is restored first. */
  purge_after?: string | null;
}

/** One view of the tab: a filter chip. */
export type VersionView = 'all' | 'main' | 'deployed' | 'unverified' | 'deleted';

/** The chips in the order the toolbar shows them. */
export const VERSION_VIEWS: readonly VersionView[] = ['all', 'main', 'deployed', 'unverified', 'deleted'];

/**
 * The chip's text.
 *
 * @param view - The view.
 * @param mainBranch - The pacticipant's main branch, when it has one.
 * @returns E.g. `All`, `main`, `Deployed`.
 */
export function viewLabel(view: VersionView, mainBranch: string | null | undefined): string {
  switch (view) {
    case 'all':
      return 'All';
    case 'main':
      return mainBranch || 'Main branch';
    case 'deployed':
      return 'Deployed';
    case 'unverified':
      return 'Unverified';
    case 'deleted':
      return 'Deleted';
  }
}

/**
 * The chips this pacticipant can use. The main-branch chip needs a main branch.
 *
 * @param mainBranch - The pacticipant's main branch.
 * @returns The views, in order.
 */
export function availableViews(mainBranch: string | null | undefined): VersionView[] {
  return VERSION_VIEWS.filter((view) => view !== 'main' || Boolean(mainBranch));
}

/**
 * The Matrix page with the pacts of one version (the row menu's **Pacts of this version**).
 *
 * @param slug - The pacticipant's handle.
 * @param number - The version number.
 * @returns The page address.
 */
export function versionMatrixHref(slug: string, number: string): string {
  const query = matrixQueryParams({
    selectors: [{ pacticipant: slug, scope: 'version', value: number, latest: false }],
    latestby: null,
    limit: 100,
  });
  return `${MATRIX_ROUTE}?${query.toString()}`;
}

/**
 * The Can I deploy page asking about one version (the row menu's **Can I deploy this?**).
 *
 * @param slug - The pacticipant's handle.
 * @param number - The version number.
 * @returns The page address.
 */
export function versionCanIDeployHref(slug: string, number: string): string {
  return `${CAN_I_DEPLOY_ROUTE}?${new URLSearchParams({ pacticipant: slug, version: number }).toString()}`;
}

/**
 * Why a version number cannot be addressed through the proxies, or `null`.
 *
 * @param number - The version number from the route.
 * @returns The refusal, or `null`.
 */
export function versionNumberProblem(number: string): string | null {
  if (!number) return 'Give the version number.';
  if (number.length > MAX_VERSION_LENGTH) return `A version number is at most ${MAX_VERSION_LENGTH} characters.`;
  if (number.includes('/')) return 'A version number with a / cannot be addressed: it is one path segment.';
  if (/[\u0000-\u001f\u007f]/.test(number)) return 'A version number has no control characters.';
  return null;
}

/**
 * Why a tag cannot be put on a version, or `null`. A tag may contain `/` (`feat/new-invoice`).
 *
 * @param tag - The tag as typed.
 * @returns The refusal, or `null`.
 */
export function tagProblem(tag: string): string | null {
  return labelProblem(tag, 'tag');
}

/**
 * The REST path of one version below `/v1/tenants/{slug}`, or `null` when the handle or number
 * cannot be addressed.
 *
 * @param pacticipantPath - The pacticipant's REST path (`pacticipants/{handle}`), or `null`.
 * @param number - The version number, exactly as recorded.
 * @param suffix - E.g. `restore` or `tags/prod`; empty for the version itself.
 * @returns The path, or `null`.
 */
export function versionProxyPath(pacticipantPath: string | null, number: string, suffix = ''): string | null {
  if (pacticipantPath === null || versionNumberProblem(number)) return null;
  const base = `${pacticipantPath}/versions/${encodeURIComponent(number)}`;
  return suffix ? `${base}/${suffix}` : base;
}

/**
 * A tag as a path tail: each `/`-separated part encoded, the `/` kept (REST's `{tag:path}`).
 *
 * @param tag - The tag.
 * @returns E.g. `feat/new%20invoice`.
 */
export function tagPathSegment(tag: string): string {
  return tag.split('/').map(encodeURIComponent).join('/');
}

/**
 * Whether a version matches the search: its number, a branch or a tag contains the text
 * (ignoring case).
 *
 * @param version - The version.
 * @param query - The search text; empty matches everything.
 * @returns Whether it matches.
 */
export function matchesSearch(version: PacticipantVersion, query: string): boolean {
  const text = query.trim().toLowerCase();
  if (!text) return true;
  return [version.number, ...version.branches, ...version.tags].some((value) => value.toLowerCase().includes(text));
}

/**
 * What the search covered, when it did not cover every version: the search reads only the
 * versions loaded so far, and says so.
 *
 * @param query - The search text.
 * @param loaded - How many versions are loaded.
 * @param more - Whether more pages exist.
 * @returns The note, or `null` when there is no search or every version is loaded.
 */
export function searchScopeNote(query: string, loaded: number, more: boolean): string | null {
  if (!query.trim() || !more) return null;
  return `Searching the ${loaded} versions loaded so far. Load more to search further.`;
}

/** One environment a version runs in now. */
export interface RunningIn {
  /** The environment's display name. */
  environment: string;
  production: boolean;
  /** `deployed` (a deployment) or `released` (a supported release). */
  kind: 'deployed' | 'released';
}

/**
 * Where each version runs now, by version number, from the environments roll-up.
 *
 * @param environments - What each environment runs of the pacticipant.
 * @returns Version number → environments, each environment once per version.
 */
export function runningInByVersion(environments: PacticipantEnvironment[]): Map<string, RunningIn[]> {
  const byVersion = new Map<string, RunningIn[]>();
  const add = (version: string, entry: RunningIn) => {
    const list = byVersion.get(version) ?? [];
    if (!list.some((item) => item.environment === entry.environment)) list.push(entry);
    byVersion.set(version, list);
  };
  for (const environment of environments) {
    const name = environment.displayName || environment.name;
    for (const deployed of environment.deployed) {
      add(deployed.version, { environment: name, production: environment.production, kind: 'deployed' });
    }
    for (const released of environment.released) {
      add(released.version, { environment: name, production: environment.production, kind: 'released' });
    }
  }
  return byVersion;
}

/**
 * The environments whose lists could not be read: the Deployed view and the delete guard then
 * cannot be sure, and the tab says which.
 *
 * @param environments - The roll-up.
 * @returns Their display names.
 */
export function unreadEnvironments(environments: PacticipantEnvironment[]): string[] {
  return environments.filter((environment) => environment.error).map((e) => e.displayName || e.name);
}

/**
 * Why a version cannot be deleted from the tab, or `null`. A version that runs somewhere is
 * refused here (REST refuses it too); the tab never sends `force`.
 *
 * @param number - The version number.
 * @param running - Where it runs now.
 * @returns E.g. `3.3.2 is running in production. Record its undeployment first.`
 */
export function deleteBlock(number: string, running: RunningIn[] | undefined): string | null {
  if (!running || running.length === 0) return null;
  const names = running.map((entry) => entry.environment);
  const where = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
  return `${number} is running in ${where}. Record its undeployment first.`;
}

/**
 * The consumer versions of this pacticipant whose pacts have no verification result, from its
 * matrix: the Unverified view. A provider's own versions are never "unverified" here — they are
 * the ones that verify.
 *
 * @param rows - The matrix rows of the pacticipant.
 * @param slug - Its handle.
 * @returns Version numbers, each once, in the matrix's order.
 */
export function unverifiedVersionNumbers(rows: MatrixRow[], slug: string): string[] {
  const numbers: string[] = [];
  for (const row of rows) {
    const version = row.consumer.version;
    if (row.consumer.slug !== slug || !version || row.verification) continue;
    if (!numbers.includes(version)) numbers.push(version);
  }
  return numbers;
}

/** What a bulk action did to each selected version. */
export interface BulkResult {
  /** The versions it changed. */
  done: string[];
  /** The versions REST refused, with REST's reason. */
  failed: { number: string; error: string }[];
  /** The versions it did not send, with why (a deployed version is never deleted). */
  skipped: { number: string; reason: string }[];
}

/**
 * The one line a bulk action leaves under the bar.
 *
 * @param action - `tag` (with the tag) or `delete`.
 * @param result - What happened to each version.
 * @param tag - The tag, for `tag`.
 * @returns The tone and the sentence; every version not changed is named with its reason.
 */
export function bulkOutcome(
  action: 'tag' | 'delete',
  result: BulkResult,
  tag = '',
): { tone: 'ok' | 'danger'; text: string } {
  const count = result.done.length;
  const noun = count === 1 ? 'version' : 'versions';
  const head =
    action === 'tag'
      ? count
        ? `Tagged ${count} ${noun} with ${tag}.`
        : `No version was tagged with ${tag}.`
      : count
        ? `Deleted ${count} ${noun}. They can be restored from Deleted until they are purged.`
        : 'No version was deleted.';
  const problems = [
    ...result.skipped.map((item) => `${item.number}: ${item.reason}`),
    ...result.failed.map((item) => `${item.number}: ${item.error}`),
  ];
  if (problems.length === 0) return { tone: 'ok', text: head };
  return { tone: 'danger', text: `${head} Not changed — ${problems.join(' ')}` };
}

/**
 * Run one async step per item, a few at a time, keeping the items' order in the answers.
 *
 * @param items - The items.
 * @param step - The step.
 * @param batch - How many at once.
 * @returns The answers, in the items' order.
 */
export async function inBatches<T, R>(items: T[], step: (item: T) => Promise<R>, batch = VERSION_BATCH): Promise<R[]> {
  const answers: R[] = [];
  for (let start = 0; start < items.length; start += batch) {
    answers.push(...(await Promise.all(items.slice(start, start + batch).map(step))));
  }
  return answers;
}

/**
 * What the tab says when a view has no version.
 *
 * @param name - The pacticipant's name.
 * @param view - The view.
 * @param searched - Whether a search narrowed it.
 * @returns The sentence.
 */
export function emptyVersionsStatement(name: string, view: VersionView, searched: boolean): string {
  if (searched) return 'No loaded version matches the search.';
  switch (view) {
    case 'all':
      return `Nothing published under ${name} yet. Publish a pact, or record one from a mock.`;
    case 'main':
      return 'No version was recorded on the main branch yet.';
    case 'deployed':
      return 'No version runs in an environment now. Record a deployment to see it here.';
    case 'unverified':
      return 'Every pact this pacticipant published has a verification result.';
    case 'deleted':
      return 'No deleted version can be restored.';
  }
}

/** Who and what deleted a version, in a few words. */
export function deletedBy(version: DeletedVersion): string {
  const cause =
    version.delete_cause === 'retention'
      ? 'by a retention run'
      : version.delete_cause === 'pacticipant'
        ? 'with its pacticipant'
        : version.deleted_by_label
          ? `by ${version.deleted_by_label}`
          : '';
  const reason = version.delete_reason ? ` — ${version.delete_reason}` : '';
  return `${cause}${reason}`.trim();
}

/**
 * Why a deleted version's **Restore** is not offered, or `null`. A version deleted with its
 * pacticipant comes back when the pacticipant is restored.
 *
 * @param version - The deleted version.
 * @returns The reason, or `null`.
 */
export function restoreBlock(version: DeletedVersion): string | null {
  return version.delete_cause === 'pacticipant'
    ? 'Deleted with its pacticipant: restore the pacticipant to bring it back.'
    : null;
}

/**
 * **The same, from anywhere** for adding a tag.
 *
 * @param pacticipant - The pacticipant's handle and name.
 * @param version - The version number.
 * @param tag - The tag typed (a placeholder when empty).
 * @param tenant - The workspace handle, or empty for `{tenant}`.
 * @returns `create-version-tag` and the REST `PUT`.
 */
export function tagCommandAction(
  pacticipant: { slug: string; name: string },
  version: string,
  tag: string,
  tenant = '',
): PactAction {
  const value = tag.trim() || '<tag>';
  return {
    verb: 'create-version-tag',
    options: [
      { flag: '--pacticipant', value: pacticipant.name },
      { flag: '--version', value: version },
      { flag: '--tag', value },
    ],
    rest: {
      method: 'PUT',
      path: tenantPath(
        tenant,
        `/pacticipants/${encodeURIComponent(pacticipant.slug)}/versions/${encodeURIComponent(version)}/tags/${tagPathSegment(value)}`,
      ),
    },
  };
}

/**
 * **The same, from anywhere** for deleting or restoring a version.
 *
 * @param kind - `delete` or `restore`.
 * @param pacticipant - The pacticipant's handle and name.
 * @param version - The version number.
 * @param reason - The delete's reason, if any.
 * @param tenant - The workspace handle, or empty for `{tenant}`.
 * @returns `delete-version` / `restore-version` and the REST request.
 */
export function versionCommandAction(
  kind: 'delete' | 'restore',
  pacticipant: { slug: string; name: string },
  version: string,
  reason = '',
  tenant = '',
): PactAction {
  const base = `/pacticipants/${encodeURIComponent(pacticipant.slug)}/versions/${encodeURIComponent(version)}`;
  if (kind === 'restore') {
    return {
      verb: 'restore-version',
      options: [
        { flag: '--pacticipant', value: pacticipant.name },
        { flag: '--version', value: version },
      ],
      rest: { method: 'POST', path: tenantPath(tenant, `${base}/restore`) },
    };
  }
  const why = reason.trim();
  return {
    verb: 'delete-version',
    options: [
      { flag: '--pacticipant', value: pacticipant.name },
      { flag: '--version', value: version },
      { flag: '--reason', value: why },
    ],
    rest: { method: 'DELETE', path: tenantPath(tenant, `${base}${why ? `?reason=${encodeURIComponent(why)}` : ''}`) },
  };
}
