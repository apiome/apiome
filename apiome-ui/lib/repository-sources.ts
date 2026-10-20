/**
 * The Sources tab of the Versions dashboard — the browser-side model (REPO-5.7, #2792).
 *
 * A project can source from several repository files (one per service); each import of one of
 * them produces a version that merges every contributing file (`lib/repository-merge.ts`). The
 * tab reads `GET /api/projects/{projectId}/repository-sources?version=…` (a BFF over apiome-rest's
 * `…/projects/{project_ref}/repository-sources`) and shows the contributing files and where every
 * class and path of the chosen version came from. This module is the reply's shape and the pure
 * helpers the panel draws with.
 */

/** One repository file contributing to the project. */
export interface ProjectRepositorySource {
  id: string;
  repository_id: string;
  repository_full_name: string | null;
  provider: string | null;
  branch: string;
  path: string;
  /** Merge order: 1 contributed first. */
  precedence: number;
  first_version_id: string | null;
  last_version_id: string | null;
  last_version_label: string | null;
  last_blob_sha: string | null;
  /** Classes of the reported version this file defines. */
  class_count: number;
  /** Paths of the reported version this file defines. */
  path_count: number;
  created_at: string;
  updated_at: string;
}

/** Where a class or path came from (snapshotted at import time). */
export interface ProvenanceSource {
  source_id: string | null;
  repository_id: string | null;
  repository_full_name: string;
  branch: string;
  path: string;
  blob_sha: string | null;
  /** Set when a merge carried the entity forward from that version. */
  carried_from_version_id: string | null;
}

/** A class or path of the version and its source (null: no repository defined it). */
export interface EntityProvenance {
  kind: 'class' | 'path';
  key: string;
  source: ProvenanceSource | null;
}

/** The BFF's reply. */
export interface ProjectRepositorySourcesReply {
  project_id: string;
  sources: ProjectRepositorySource[];
  version: { id: string; version_label: string | null } | null;
  entities: EntityProvenance[];
  counts: { classes: number; paths: number; attributed: number; unattributed: number };
}

/** The source filter: every entity, one source row, or entities no repository defined. */
export type SourceFilter = 'all' | 'none' | string;

/** The kind filter. */
export type KindFilter = 'all' | 'class' | 'path';

/** How an entity reached the version. */
export type EntityOrigin = 'imported' | 'carried' | 'unattributed';

/** Labels for {@link EntityOrigin}, as the table shows them. */
export const ENTITY_ORIGIN_LABEL: Record<EntityOrigin, string> = {
  imported: 'Imported',
  carried: 'Carried forward',
  unattributed: 'Not from a repository',
};

/** Badge tones for {@link EntityOrigin}. */
export const ENTITY_ORIGIN_TONE: Record<EntityOrigin, 'ok' | 'accent' | 'neutral'> = {
  imported: 'ok',
  carried: 'accent',
  unattributed: 'neutral',
};

/**
 * How an entity reached the version.
 *
 * @param entity - The class or path.
 * @returns `imported` when this version's import wrote it, `carried` when a merge carried it
 *   forward from the parent, `unattributed` when no repository defined it.
 */
export function entityOrigin(entity: EntityProvenance): EntityOrigin {
  if (!entity.source) return 'unattributed';
  return entity.source.carried_from_version_id ? 'carried' : 'imported';
}

/**
 * A source as one line: `owner/name · branch:path`.
 *
 * @param source - A contributing source or an entity's provenance.
 * @returns The label (the repository id stands in for a missing name).
 */
export function sourceLabel(
  source: Pick<ProjectRepositorySource, 'repository_full_name' | 'repository_id' | 'branch' | 'path'> |
    Pick<ProvenanceSource, 'repository_full_name' | 'repository_id' | 'branch' | 'path'>,
): string {
  const name = source.repository_full_name || source.repository_id || 'Unknown repository';
  return `${name} · ${source.branch}:${source.path}`;
}

/**
 * The entities that pass the panel's filters.
 *
 * @param entities - Every class and path of the version (classes first, each by key).
 * @param filters - Source, kind and a case-insensitive search over the name and the source.
 * @returns The matching entities, order kept.
 */
export function filterEntities(
  entities: readonly EntityProvenance[],
  filters: { source: SourceFilter; kind: KindFilter; query: string },
): EntityProvenance[] {
  const needle = filters.query.trim().toLowerCase();
  return entities.filter((entity) => {
    if (filters.kind !== 'all' && entity.kind !== filters.kind) return false;
    if (filters.source === 'none' && entity.source) return false;
    if (filters.source !== 'all' && filters.source !== 'none' && entity.source?.source_id !== filters.source) {
      return false;
    }
    if (!needle) return true;
    const haystack = `${entity.key} ${entity.source ? sourceLabel(entity.source) : ''}`.toLowerCase();
    return haystack.includes(needle);
  });
}

/**
 * The one-sentence summary above the table.
 *
 * @param reply - The BFF reply.
 * @returns e.g. `2 repository files contribute. 12 of 14 classes and paths come from a repository.`
 */
export function provenanceSummary(reply: Pick<ProjectRepositorySourcesReply, 'sources' | 'counts'>): string {
  const files = reply.sources.length;
  const total = reply.counts.classes + reply.counts.paths;
  const filesPart =
    files === 0
      ? 'No repository file contributes to this project.'
      : `${files} repository file${files === 1 ? '' : 's'} contribute${files === 1 ? 's' : ''}.`;
  if (total === 0) return filesPart;
  return `${filesPart} ${reply.counts.attributed} of ${total} classes and paths come from a repository.`;
}

/**
 * Validate the BFF's reply.
 *
 * @param payload - The parsed JSON.
 * @returns The reply, or null when it is not one.
 */
export function parseRepositorySourcesReply(payload: unknown): ProjectRepositorySourcesReply | null {
  const record = payload as Partial<ProjectRepositorySourcesReply> | null;
  if (!record || typeof record !== 'object') return null;
  if (!Array.isArray(record.sources) || !Array.isArray(record.entities) || !record.counts) return null;
  return record as ProjectRepositorySourcesReply;
}
