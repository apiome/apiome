/**
 * Reporting federation merges to apiome-rest — V2-REPO-8.2 (#2806).
 *
 * The multi-repository merge (REPO-5.7) runs here, in the import. Its history and audit trail
 * live in apiome-rest (`project_federation_merges`, apiome-db V303), which writes each history
 * row and its hash-chained `access_audit` row (`repository.federation_merged` / `…_conflicted` /
 * `…_replaced`) in one transaction. So once federation has acted on a repository-file import,
 * the import reports what happened:
 *
 * - **merged** — a multi-file merge wrote a version (reported after the import commits);
 * - **conflicted** — two files define the same class or path; the import fails and writes
 *   nothing, and the report carries the importing file's definition of each collision (apiome-rest
 *   reads the contributing file's side from the parent version);
 * - **replaced** — federation is off and the import dropped other files' content.
 *
 * {@link buildFederationReport} is pure. {@link postFederationMerge} sends it as the importing
 * user; it never throws — a report that cannot be delivered is returned as an error message for
 * the import log, because the import's own outcome must not depend on it.
 */

import { createRestAuthHeaders, REST_API_BASE_URL } from './rest-auth';
import type { MergeSource, RepositoryMergePlan } from './repository-merge';

/** What federation did to an import. */
export type FederationMergeStatus = 'merged' | 'conflicted' | 'replaced';

/** One source's side of a conflict, as reported. */
export interface FederationConflictSideReport {
  role: 'existing' | 'incoming';
  repositoryFullName: string;
  branch: string;
  path: string;
  /** The importing file's definition; omitted for the existing side (apiome-rest reads it). */
  definition?: unknown;
}

/** The body of `POST …/projects/{project}/federation-merges`. */
export interface FederationMergeReport {
  status: FederationMergeStatus;
  versionId?: string;
  parentVersionId?: string;
  repositoryId: string;
  repositoryFullName: string;
  branch: string;
  path: string;
  sourceCount: number;
  classesCarried: number;
  pathsCarried: number;
  removedCount: number;
  sources: Array<{ repositoryFullName: string; branch: string; path: string; precedence: number | null }>;
  conflicts: Array<{ kind: 'class' | 'path'; key: string; sources: FederationConflictSideReport[] }>;
  conflictCount: number;
}

/** Most conflicts a report carries (apiome-rest's limit); `conflictCount` keeps the full number. */
export const MAX_REPORTED_CONFLICTS = 50;

/** Who is reporting, and where. */
export interface FederationReportCaller {
  userId: string;
  tenantId: string;
  tenantSlug: string;
}

/**
 * Decide what, if anything, a planned merge should report.
 *
 * @param plan - The merge plan.
 * @param options - `committed`: the import wrote its version (merged / replaced are reported only
 *   then); `versionId`: that version.
 * @returns The status to report, or null when federation did nothing worth recording (a
 *   single-file project's import).
 */
export function federationStatusFor(
  plan: RepositoryMergePlan,
  options: { committed: boolean },
): FederationMergeStatus | null {
  if (plan.conflicts.length > 0) return 'conflicted';
  if (!options.committed) return null;
  if (plan.mode === 'multi-source') return 'merged';
  if (plan.dropped.length > 0) return 'replaced';
  return null;
}

/**
 * Build the report for one import.
 *
 * @param input - The plan, the importing file, the versions involved, how many paths were
 *   carried, and how to find the importing file's definition of a class or path.
 * @returns The report body.
 */
export function buildFederationReport(input: {
  status: FederationMergeStatus;
  plan: RepositoryMergePlan;
  incoming: MergeSource;
  versionId?: string | null;
  parentVersionId?: string | null;
  pathsCarried: number;
  incomingDefinition: (kind: 'class' | 'path', key: string) => unknown;
}): FederationMergeReport {
  const { plan, incoming } = input;
  const side = (role: 'existing' | 'incoming', source: MergeSource): FederationConflictSideReport => ({
    role,
    repositoryFullName: source.repositoryFullName,
    branch: source.branch,
    path: source.path,
  });
  return {
    status: input.status,
    ...(input.versionId && input.status !== 'conflicted' ? { versionId: input.versionId } : {}),
    ...(input.parentVersionId ? { parentVersionId: input.parentVersionId } : {}),
    repositoryId: incoming.repositoryId,
    repositoryFullName: incoming.repositoryFullName,
    branch: incoming.branch,
    path: incoming.path,
    sourceCount: plan.sources.length,
    classesCarried: plan.carried.filter((e) => e.kind === 'class').length,
    pathsCarried: input.pathsCarried,
    removedCount: plan.removed.length + plan.dropped.length,
    sources: plan.sources.map((s) => ({
      repositoryFullName: s.repositoryFullName,
      branch: s.branch,
      path: s.path,
      precedence: s.precedence,
    })),
    conflicts: plan.conflicts.slice(0, MAX_REPORTED_CONFLICTS).map((c) => ({
      kind: c.kind,
      key: c.key,
      sources: [
        side('existing', c.existing),
        { ...side('incoming', c.incoming), definition: input.incomingDefinition(c.kind, c.key) ?? null },
      ],
    })),
    conflictCount: plan.conflicts.length,
  };
}

/**
 * Send a report to apiome-rest as the importing user.
 *
 * @param caller - The importing user and tenant.
 * @param projectId - The project the import targets.
 * @param report - From {@link buildFederationReport}.
 * @param fetchImpl - Injected by tests.
 * @returns null when recorded, otherwise why not (for the import log). Never throws.
 */
export async function postFederationMerge(
  caller: FederationReportCaller,
  projectId: string,
  report: FederationMergeReport,
  fetchImpl: typeof fetch = fetch,
): Promise<string | null> {
  const url =
    `${REST_API_BASE_URL}/tenants/${encodeURIComponent(caller.tenantSlug)}` +
    `/projects/${encodeURIComponent(projectId)}/federation-merges`;
  try {
    const response = await fetchImpl(url, {
      method: 'POST',
      headers: createRestAuthHeaders({ user_id: caller.userId, current_tenant_id: caller.tenantId }),
      body: JSON.stringify(report),
      cache: 'no-store',
    });
    if (response.ok) return null;
    return `apiome-rest answered ${response.status}`;
  } catch (error) {
    return error instanceof Error && error.message ? error.message : 'apiome-rest is not reachable';
  }
}
