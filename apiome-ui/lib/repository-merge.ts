/**
 * Multi-repository merge into one API surface (REPO-5.7, #2792) — the pure rules.
 *
 * A project can source from several repository files (one per service). Every import of a
 * repository file into such a project produces a new version holding the union of the
 * contributing files:
 *
 * - what the importing file defines now (its classes and paths);
 * - every class and path the *other* contributing files defined in the parent version, carried
 *   forward unchanged;
 * - classes and paths no repository defined (edited in Apiome, or imported before REPO-5.7),
 *   carried forward too unless the importing file now defines the same name.
 *
 * What the importing file defined in the parent but no longer defines is dropped — a deletion in
 * the repository propagates. Two different files defining the same class name or the same
 * pathname is a **conflict**: the import fails with a message naming both files, and nothing is
 * written. Precedence (1 = the file that contributed first) orders the merged surface and the
 * conflict list; it never decides a conflict.
 *
 * A project whose parent version holds nothing from another file is in **single-source** mode and
 * behaves exactly as before REPO-5.7: the new version holds only the importing file's content.
 *
 * **Federation switch (V2-REPO-8.2, #2806).** A project whose federation is switched off is always
 * planned in single-source mode: the importing file replaces the surface. When the parent held
 * another file's content, that content is listed in `dropped` so the import can record the
 * replacement in the project's merge history.
 *
 * This module has no I/O; `lib/db/repository-merge.ts` reads the parent version and writes the
 * result.
 */

/** The two kinds of entity a provenance row attributes. */
export type MergeEntityKind = 'class' | 'path';

/** A repository file that contributes (or is about to contribute) to a project. */
export interface MergeSource {
  /** `project_repository_sources.id`, or null when the file has no source row yet. */
  sourceId: string | null;
  repositoryId: string;
  /** `owner/name` of the repository, for messages and the provenance snapshot. */
  repositoryFullName: string;
  branch: string;
  path: string;
  /** Merge order: 1 contributed first. Null for a file that has not contributed yet. */
  precedence: number | null;
  /** Blob the entity was last read from, when known. */
  blobSha?: string | null;
}

/** A class or path of the parent version, with the file that defined it (null: none). */
export interface ParentEntity {
  kind: MergeEntityKind;
  key: string;
  source: MergeSource | null;
}

/** A class or path carried forward from the parent version into the new one. */
export interface CarriedEntity {
  kind: MergeEntityKind;
  key: string;
  /** The file that defined it, or null for content no repository defined. */
  source: MergeSource | null;
}

/** Two contributing files defining the same class or path. */
export interface MergeConflict {
  kind: MergeEntityKind;
  key: string;
  /** The file that defined it in the parent version. */
  existing: MergeSource;
  /** The file being imported. */
  incoming: MergeSource;
}

/** Inputs to {@link planRepositoryMerge}. */
export interface RepositoryMergeInput {
  /** The repository file being imported. */
  incoming: MergeSource;
  /** Class names the importing file produces (after naming options are applied). */
  incomingClasses: readonly string[];
  /** Pathnames the importing file produces. */
  incomingPaths: readonly string[];
  /** Every class and path of the parent version (empty for a project's first version). */
  parentEntities: readonly ParentEntity[];
  /**
   * The project's federation switch (V2-REPO-8.2). `false` plans single-source whatever the parent
   * holds. Defaults to `true`.
   */
  federation?: boolean;
}

/** The outcome of {@link planRepositoryMerge}. */
export interface RepositoryMergePlan {
  /** `multi-source` when the parent holds content from another file; otherwise `single-source`. */
  mode: 'single-source' | 'multi-source';
  /** Conflicts, ordered by kind (classes first) then key. Non-empty means the import must fail. */
  conflicts: MergeConflict[];
  /** Entities carried forward, ordered by source precedence (unattributed last), kind, key. */
  carried: CarriedEntity[];
  /** Unattributed parent entities the importing file now defines (replaced, with a warning). */
  superseded: CarriedEntity[];
  /** Parent entities the importing file defined but no longer defines (dropped). */
  removed: CarriedEntity[];
  /** Every file the new version is built from, in precedence order (the importing file included). */
  sources: MergeSource[];
  /**
   * Federation off (V2-REPO-8.2): parent content that is not the importing file's and is dropped
   * because the import replaces the surface. Non-empty only when the parent held another file's
   * content. Ordered like `carried`.
   */
  dropped: CarriedEntity[];
}

/** Error thrown by the import when a merge plan has conflicts. */
export class RepositoryMergeConflictError extends Error {
  readonly conflicts: MergeConflict[];

  constructor(conflicts: MergeConflict[], projectName?: string | null) {
    super(formatMergeConflictMessage(conflicts, projectName));
    this.name = 'RepositoryMergeConflictError';
    this.conflicts = conflicts;
  }
}

/** Stable identity of a repository file lineage. */
export function sourceLineageKey(source: Pick<MergeSource, 'repositoryId' | 'branch' | 'path'>): string {
  return `${source.repositoryId}\u0000${source.branch}\u0000${source.path}`;
}

/** True when both refer to the same repository file lineage (repository, branch, path). */
export function isSameSource(
  a: Pick<MergeSource, 'repositoryId' | 'branch' | 'path'>,
  b: Pick<MergeSource, 'repositoryId' | 'branch' | 'path'>,
): boolean {
  return sourceLineageKey(a) === sourceLineageKey(b);
}

/** Human label for a source: `owner/name (branch:path)`. */
export function formatMergeSource(source: Pick<MergeSource, 'repositoryFullName' | 'branch' | 'path'>): string {
  return `${source.repositoryFullName} (${source.branch}:${source.path})`;
}

const KIND_ORDER: Record<MergeEntityKind, number> = { class: 0, path: 1 };

/** Sort key for a source: precedence first, never-contributed files last, then lineage. */
function compareSources(a: MergeSource | null, b: MergeSource | null): number {
  if (a === b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  const pa = a.precedence ?? Number.MAX_SAFE_INTEGER;
  const pb = b.precedence ?? Number.MAX_SAFE_INTEGER;
  if (pa !== pb) return pa - pb;
  return sourceLineageKey(a) < sourceLineageKey(b) ? -1 : sourceLineageKey(a) > sourceLineageKey(b) ? 1 : 0;
}

function compareEntities(a: CarriedEntity, b: CarriedEntity): number {
  return (
    compareSources(a.source, b.source) ||
    KIND_ORDER[a.kind] - KIND_ORDER[b.kind] ||
    (a.key < b.key ? -1 : a.key > b.key ? 1 : 0)
  );
}

/**
 * Plan the merge of one repository file into a project's next version.
 *
 * @param input - The importing file, what it produces, and the parent version's entities.
 * @returns The plan: mode, conflicts, what is carried forward, superseded and removed, and the
 *   contributing files in precedence order. The plan is deterministic for a given input.
 */
export function planRepositoryMerge(input: RepositoryMergeInput): RepositoryMergePlan {
  const { incoming } = input;
  const incomingKeys: Record<MergeEntityKind, Set<string>> = {
    class: new Set(input.incomingClasses),
    path: new Set(input.incomingPaths),
  };

  const multiSource = input.parentEntities.some(
    (entity) => entity.source !== null && !isSameSource(entity.source, incoming),
  );
  if (!multiSource || input.federation === false) {
    const dropped: CarriedEntity[] = multiSource
      ? input.parentEntities
          .filter((entity) => !entity.source || !isSameSource(entity.source, incoming))
          .map((entity) => ({ kind: entity.kind, key: entity.key, source: entity.source }))
          .sort(compareEntities)
      : [];
    return {
      mode: 'single-source',
      conflicts: [],
      carried: [],
      superseded: [],
      removed: [],
      sources: [incoming],
      dropped,
    };
  }

  const conflicts: MergeConflict[] = [];
  const carried: CarriedEntity[] = [];
  const superseded: CarriedEntity[] = [];
  const removed: CarriedEntity[] = [];

  for (const entity of input.parentEntities) {
    const definedNow = incomingKeys[entity.kind].has(entity.key);
    const item: CarriedEntity = { kind: entity.kind, key: entity.key, source: entity.source };
    if (entity.source && isSameSource(entity.source, incoming)) {
      // The importing file's own previous content: replaced by what it defines now.
      if (!definedNow) removed.push(item);
    } else if (entity.source) {
      if (definedNow) {
        conflicts.push({ kind: entity.kind, key: entity.key, existing: entity.source, incoming });
      } else {
        carried.push(item);
      }
    } else if (definedNow) {
      superseded.push(item);
    } else {
      carried.push(item);
    }
  }

  conflicts.sort(
    (a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0),
  );
  carried.sort(compareEntities);
  superseded.sort(compareEntities);
  removed.sort(compareEntities);

  const byLineage = new Map<string, MergeSource>();
  byLineage.set(sourceLineageKey(incoming), incoming);
  for (const entity of carried) {
    if (entity.source && !byLineage.has(sourceLineageKey(entity.source))) {
      byLineage.set(sourceLineageKey(entity.source), entity.source);
    }
  }
  const sources = [...byLineage.values()].sort(compareSources);

  return { mode: 'multi-source', conflicts, carried, superseded, removed, sources, dropped: [] };
}

/** How many conflicts the error message spells out before summarizing the rest. */
export const MAX_LISTED_CONFLICTS = 10;

/**
 * The error a failed merge reports: every conflict names the class or path and both files.
 *
 * @param conflicts - The plan's conflicts (non-empty).
 * @param projectName - The project, when known.
 * @returns A message such as
 *   `Repository merge conflict in project "Shop": 1 definition collides. class "User" is defined by
 *   acme/users (main:openapi.yaml) and acme/billing (main:openapi.yaml). …`
 */
export function formatMergeConflictMessage(
  conflicts: readonly MergeConflict[],
  projectName?: string | null,
): string {
  const where = projectName ? ` in project "${projectName}"` : '';
  const count = conflicts.length;
  const head = `Repository merge conflict${where}: ${count} definition${count === 1 ? '' : 's'} collide${count === 1 ? 's' : ''}.`;
  const lines = conflicts.slice(0, MAX_LISTED_CONFLICTS).map(
    (c) =>
      `${c.kind} "${c.key}" is defined by ${formatMergeSource(c.existing)} and ${formatMergeSource(c.incoming)}.`,
  );
  const more = count > MAX_LISTED_CONFLICTS ? [`…and ${count - MAX_LISTED_CONFLICTS} more.`] : [];
  const fix =
    'Each class and path must come from one repository: rename or remove the duplicate in one of the files, then import again.';
  return [head, ...lines, ...more, fix].join(' ');
}

/**
 * One-line summary of a multi-source plan for the import log.
 *
 * @param plan - A plan in `multi-source` mode.
 * @returns e.g. `Merging 3 repository files: carrying forward 4 classes and 2 paths from other files.`
 */
export function describeMergePlan(plan: RepositoryMergePlan): string {
  const classes = plan.carried.filter((e) => e.kind === 'class').length;
  const paths = plan.carried.filter((e) => e.kind === 'path').length;
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 'es'}`;
  return (
    `Merging ${plan.sources.length} repository file${plan.sources.length === 1 ? '' : 's'}: ` +
    `carrying forward ${plural(classes, 'class')} and ${paths} path${paths === 1 ? '' : 's'} from other files.`
  );
}
