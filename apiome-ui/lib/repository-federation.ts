/**
 * Multi-repository federation, browser side — V2-REPO-8.2 (#2806).
 *
 * The screens' model of the federation switch and the merge history (apiome-rest owns both,
 * apiome-db V303): typed parsers that refuse malformed replies, the words and tones for each
 * merge status, and {@link conflictDiff} — the line diff between two sources' definitions of one
 * class or path that the history shows for a conflict.
 */

import { diffLines } from 'diff';

/** What federation did to an import. */
export type FederationMergeStatus = 'merged' | 'conflicted' | 'replaced';

/** A repository file, as the history shows it. */
export interface FederationSourceRef {
  repositoryFullName: string;
  branch: string;
  path: string;
  precedence: number | null;
}

/** One source's side of a conflict. */
export interface FederationConflictSide {
  role: 'existing' | 'incoming';
  repositoryFullName: string;
  branch: string;
  path: string;
  definition: unknown;
}

/** A class or path two files both define. */
export interface FederationConflict {
  kind: 'class' | 'path';
  key: string;
  sources: FederationConflictSide[];
}

/** One merge-history row. */
export interface FederationMerge {
  id: string;
  projectId: string;
  projectName: string | null;
  status: FederationMergeStatus;
  versionId: string | null;
  versionLabel: string | null;
  repositoryFullName: string;
  branch: string;
  path: string;
  sourceCount: number;
  classesCarried: number;
  pathsCarried: number;
  removedCount: number;
  conflictCount: number;
  sources: FederationSourceRef[];
  conflicts: FederationConflict[];
  createdAt: string;
}

/** One line of a conflict diff. */
export interface DiffLine {
  text: string;
  /** `same`, or which side only has it. */
  change: 'same' | 'existing' | 'incoming';
}

/** Labels for each status. */
export const FEDERATION_STATUS_LABEL: Record<FederationMergeStatus, string> = {
  merged: 'Merged',
  conflicted: 'Conflict',
  replaced: 'Replaced',
};

/** Badge tones for each status. */
export const FEDERATION_STATUS_TONE: Record<FederationMergeStatus, 'ok' | 'danger' | 'warn'> = {
  merged: 'ok',
  conflicted: 'danger',
  replaced: 'warn',
};

/** What the switch does, in the words the Sources tab uses. */
export const FEDERATION_SWITCH_COPY = {
  on: 'Each repository file you import is merged with the other contributing files into one API.',
  off: 'Each repository file you import replaces the API: content other files defined is not carried forward.',
} as const;

const STATUSES: readonly FederationMergeStatus[] = ['merged', 'conflicted', 'replaced'];

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function parseSide(value: unknown): FederationConflictSide | null {
  if (!isObject(value) || typeof value.repositoryFullName !== 'string') return null;
  return {
    role: value.role === 'incoming' ? 'incoming' : 'existing',
    repositoryFullName: value.repositoryFullName,
    branch: str(value.branch) ?? '',
    path: str(value.path) ?? '',
    definition: value.definition ?? null,
  };
}

function parseMerge(value: unknown): FederationMerge | null {
  if (!isObject(value) || typeof value.id !== 'string' || !STATUSES.includes(value.status as FederationMergeStatus)) {
    return null;
  }
  const conflicts = Array.isArray(value.conflicts)
    ? value.conflicts.filter(isObject).flatMap((c) => {
        const sides = Array.isArray(c.sources) ? c.sources.map(parseSide).filter((s): s is FederationConflictSide => !!s) : [];
        return typeof c.key === 'string' && sides.length === 2
          ? [{ kind: c.kind === 'path' ? ('path' as const) : ('class' as const), key: c.key, sources: sides }]
          : [];
      })
    : [];
  const sources = Array.isArray(value.sources)
    ? value.sources.filter(isObject).flatMap((s) =>
        typeof s.repositoryFullName === 'string'
          ? [
              {
                repositoryFullName: s.repositoryFullName,
                branch: str(s.branch) ?? '',
                path: str(s.path) ?? '',
                precedence: typeof s.precedence === 'number' ? s.precedence : null,
              },
            ]
          : [],
      )
    : [];
  return {
    id: value.id,
    projectId: str(value.projectId) ?? '',
    projectName: str(value.projectName),
    status: value.status as FederationMergeStatus,
    versionId: str(value.versionId),
    versionLabel: str(value.versionLabel),
    repositoryFullName: str(value.repositoryFullName) ?? '',
    branch: str(value.branch) ?? '',
    path: str(value.path) ?? '',
    sourceCount: num(value.sourceCount),
    classesCarried: num(value.classesCarried),
    pathsCarried: num(value.pathsCarried),
    removedCount: num(value.removedCount),
    conflictCount: num(value.conflictCount),
    sources,
    conflicts,
    createdAt: str(value.createdAt) ?? '',
  };
}

/**
 * Parse a merge-history reply.
 *
 * @param payload - The BFF's JSON.
 * @returns The merges, newest first, or null when the reply is malformed.
 */
export function parseFederationMerges(payload: unknown): FederationMerge[] | null {
  if (!isObject(payload) || !Array.isArray(payload.merges)) return null;
  return payload.merges.map(parseMerge).filter((m): m is FederationMerge => m !== null);
}

/**
 * Parse the switch.
 *
 * @param payload - The BFF's JSON.
 * @returns The switch, or null when the reply is malformed.
 */
export function parseFederationSetting(payload: unknown): boolean | null {
  return isObject(payload) && typeof payload.enabled === 'boolean' ? payload.enabled : null;
}

/** A source as `owner/name (branch:path)`. */
export function sourceText(source: Pick<FederationSourceRef, 'repositoryFullName' | 'branch' | 'path'>): string {
  return `${source.repositoryFullName} (${source.branch}:${source.path})`;
}

/**
 * Describe one history row in a sentence.
 *
 * @param merge - The row.
 * @returns e.g. "Merged 3 files into 1.4.0: carried 4 classes and 2 paths from other files."
 */
export function mergeSentence(merge: FederationMerge): string {
  const into = merge.versionLabel ? ` into ${merge.versionLabel}` : '';
  switch (merge.status) {
    case 'merged':
      return (
        `Merged ${merge.sourceCount} file${merge.sourceCount === 1 ? '' : 's'}${into}: carried ` +
        `${merge.classesCarried} class${merge.classesCarried === 1 ? '' : 'es'} and ${merge.pathsCarried} ` +
        `path${merge.pathsCarried === 1 ? '' : 's'} from other files.`
      );
    case 'replaced':
      return `Federation was off: this file replaced the API${into}, dropping ${merge.removedCount} class(es) and path(s) other files defined.`;
    default:
      return (
        `${merge.conflictCount} definition${merge.conflictCount === 1 ? '' : 's'} collided with another ` +
        'repository file, so the import wrote nothing.'
      );
  }
}

/**
 * Render a definition the way the diff compares it.
 *
 * @param definition - A source's definition (or null).
 * @returns Pretty JSON with sorted keys, or a note when there is none.
 */
export function definitionText(definition: unknown): string {
  if (definition === null || definition === undefined) return '(definition not available)';
  if (isObject(definition) && definition.$truncated === true) {
    return `(definition too large to keep: ${num(definition.bytes).toLocaleString('en-US')} bytes)`;
  }
  const sorted = (value: unknown): unknown =>
    Array.isArray(value)
      ? value.map(sorted)
      : isObject(value)
        ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sorted(value[key])]))
        : value;
  return JSON.stringify(sorted(definition), null, 2);
}

/**
 * Line diff between the existing and the incoming source's definitions of one conflict.
 *
 * @param conflict - The conflict (existing side first).
 * @returns Every line, marked as shared or as only in one source.
 */
export function conflictDiff(conflict: FederationConflict): DiffLine[] {
  const existing = conflict.sources.find((s) => s.role === 'existing') ?? conflict.sources[0];
  const incoming = conflict.sources.find((s) => s.role === 'incoming') ?? conflict.sources[1];
  const out: DiffLine[] = [];
  for (const part of diffLines(definitionText(existing?.definition), definitionText(incoming?.definition))) {
    const change: DiffLine['change'] = part.added ? 'incoming' : part.removed ? 'existing' : 'same';
    for (const line of part.value.replace(/\n$/, '').split('\n')) out.push({ text: line, change });
  }
  return out;
}
