/**
 * Git-like merge preview helpers: compare OpenAPI snapshots and classify conflicts.
 */

import { compareSchemas, type DiffSummary } from './schema-diff';

/** Local resolution for merge conflict rows (#2574); server submit is a later step. */
export type MergeConflictResolutionChoice = 'mine' | 'theirs' | 'manual';

/** REST `conflicts[].kinds` values from `version_merge_routes._merge_conflict_records`. */
const KIND_ORDER = ['threeWay', 'blend', 'twoWay'] as const;

export const MERGE_CONFLICT_KIND_LABELS: Record<string, string> = {
  threeWay: 'Three-way',
  blend: 'Blend / materialize',
  twoWay: 'Two-way (divergent)',
};

/**
 * Human-readable conflict type column for merge preview `conflicts[]` rows.
 */
export function formatMergeConflictKinds(kinds: string[]): string {
  const unique = [...new Set(kinds.filter((k) => typeof k === 'string' && k.length > 0))];
  const sorted = unique.sort((a, b) => {
    const ia = KIND_ORDER.indexOf(a as (typeof KIND_ORDER)[number]);
    const ib = KIND_ORDER.indexOf(b as (typeof KIND_ORDER)[number]);
    if (ia !== -1 || ib !== -1) {
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    }
    return a.localeCompare(b);
  });
  const parts = sorted.map((k) => MERGE_CONFLICT_KIND_LABELS[k] ?? k);
  return parts.length > 0 ? parts.join(' · ') : 'Unknown';
}

/**
 * Prefer API `conflicts`; otherwise build rows from `classification.conflictPaths` (e.g. 409 replay).
 */
/** Stable key for grouping/filtering rows by `kinds` (order-independent). */
export function mergeConflictKindSignature(kinds: string[]): string {
  const uniq = [...new Set(kinds.map((k) => k.trim()).filter((k) => k.length > 0))];
  return uniq.sort().join('|');
}

export type MergeConflictRow = { path: string; kinds: string[] };

/** Rows matching optional path substring and/or conflict-kind signature. */
export function filterMergeConflictRows(
  rows: MergeConflictRow[],
  opts: { pathContains?: string; kindSignature?: string | 'all' }
): MergeConflictRow[] {
  const q = (opts.pathContains ?? '').trim().toLowerCase();
  const sig = opts.kindSignature ?? 'all';
  return rows.filter((row) => {
    if (q && !row.path.toLowerCase().includes(q)) return false;
    if (sig !== 'all' && mergeConflictKindSignature(row.kinds) !== sig) return false;
    return true;
  });
}

export function normalizeMergeConflictRows(
  conflicts: unknown,
  fallbackPaths: string[]
): Array<{ path: string; kinds: string[] }> {
  if (Array.isArray(conflicts) && conflicts.length > 0) {
    const out: Array<{ path: string; kinds: string[] }> = [];
    for (const c of conflicts) {
      if (typeof c !== 'object' || c === null) continue;
      const path = (c as { path?: unknown }).path;
      if (typeof path !== 'string') continue;
      const normalizedPath = path.trim();
      if (!normalizedPath) continue;
      const raw = (c as { kinds?: unknown }).kinds;
      const kinds = Array.isArray(raw)
        ? raw
            .filter((k): k is string => typeof k === 'string')
            .map((k) => k.trim())
            .filter((k) => k.length > 0)
        : [];
      out.push({ path: normalizedPath, kinds: kinds.length > 0 ? kinds : ['twoWay'] });
    }
    if (out.length > 0) return out;
  }
  return fallbackPaths.map((path) => ({ path, kinds: ['twoWay'] }));
}

/** Compare target vs source specs: merge source into target; blocking = modified + removed paths. */
export function classifyMergeDiff(summary: DiffSummary): {
  canAutoMerge: boolean;
  conflictPaths: string[];
  addedSchemaNames: string[];
} {
  const conflictPaths = [
    ...summary.modified.map((d) => d.path),
    ...summary.removed.map((d) => d.path),
  ];
  const addedSchemaNames = summary.added
    .filter((d) => d.itemType === 'schema' && d.path.startsWith('schemas.'))
    .map((d) => d.path.replace(/^schemas\./, ''));
  return {
    canAutoMerge: conflictPaths.length === 0,
    conflictPaths,
    addedSchemaNames,
  };
}

export async function mergePreviewFromSpecs(targetSpecJson: string, sourceSpecJson: string): Promise<{
  summary: DiffSummary;
  classification: ReturnType<typeof classifyMergeDiff>;
}> {
  const summary = compareSchemas(targetSpecJson, sourceSpecJson);
  return { summary, classification: classifyMergeDiff(summary) };
}
