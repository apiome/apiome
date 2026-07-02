/**
 * Compact revision lineage for "create copy from" context (#505).
 * Uses primary parent_version_id chain; surfaces merge_parent when present on a step.
 */

export type VersionLineageInput = {
  id: string;
  version_id: string;
  parent_version_id?: string | null;
  merge_parent_version_id?: string | null;
};

function parentOf(v: VersionLineageInput): string | null {
  const p = v.parent_version_id;
  return p && p.trim() ? p : null;
}

function mergeParentOf(v: VersionLineageInput): string | null {
  const m = v.merge_parent_version_id;
  return m && m.trim() ? m : null;
}

/** Primary ancestors from tip toward root (tip first). */
export function buildPrimaryAncestors(
  tipId: string,
  versions: VersionLineageInput[],
  maxDepth = 16
): VersionLineageInput[] {
  const byId = new Map(versions.map((v) => [v.id, v]));
  const steps: VersionLineageInput[] = [];
  let cur: string | null = tipId;
  let depth = 0;
  const seen = new Set<string>();

  while (cur && depth < maxDepth) {
    if (seen.has(cur)) break;
    seen.add(cur);
    const row = byId.get(cur);
    if (!row) break;
    steps.push(row);
    cur = parentOf(row);
    depth++;
  }
  return steps;
}

export type LineageSnippetModel = {
  /** Root → … → tip (semantic order for reading). */
  breadcrumbLabels: string[];
  /** Short revision ids for display (same order as breadcrumbLabels). */
  revisionIds: string[];
  /** If the tip has a merge parent, its label (not necessarily on the primary chain). */
  mergeParentLabel: string | null;
  /** Monospace lines for a tiny graph (may be empty). */
  asciiLines: string[];
  /** Plain sentence for screen readers. */
  screenSummary: string;
};

function shortLabel(v: VersionLineageInput): string {
  return `v${v.version_id}`;
}

/**
 * Build compact lineage description + optional ASCII fork (single merge side at any step).
 */
export function buildLineageSnippet(
  tipId: string,
  versions: VersionLineageInput[],
  opts?: { branchNamesAtTip?: string[] }
): LineageSnippetModel | null {
  const byId = new Map(versions.map((v) => [v.id, v]));
  const tip = byId.get(tipId);
  if (!tip) return null;

  const primary = buildPrimaryAncestors(tipId, versions);
  if (primary.length === 0) return null;

  const rootToTip = [...primary].reverse();
  const breadcrumbLabels = rootToTip.map(shortLabel);
  const revisionIds = rootToTip.map((v) => v.id);

  let mergeParentLabel: string | null = null;
  const tipNode = primary[0];
  const tipMerge = mergeParentOf(tipNode);
  if (tipMerge) {
    const m = byId.get(tipMerge);
    mergeParentLabel = m ? shortLabel(m) : 'unknown';
  }

  const branchSuffix =
    opts?.branchNamesAtTip && opts.branchNamesAtTip.length > 0
      ? ` Branches at this tip: ${opts.branchNamesAtTip.join(', ')}.`
      : '';

  const asciiLines = buildLinearAscii(rootToTip);

  const chainText = breadcrumbLabels.join(' → ');
  const mergeText = mergeParentLabel ? ` Merge parent: ${mergeParentLabel}.` : '';
  const screenSummary = `Source revision chain: ${chainText}.${mergeText}${branchSuffix}`.trim();

  return {
    breadcrumbLabels,
    revisionIds,
    mergeParentLabel,
    asciiLines,
    screenSummary,
  };
}

/** Compact linear "git log --oneline"-style graph (merge shown as text separately). */
function buildLinearAscii(rootToTip: VersionLineageInput[]): string[] {
  const n = rootToTip.length;
  if (n === 0) return [];
  if (n === 1) {
    return [`  o  ${shortLabel(rootToTip[0])}`];
  }
  const segments = Array(n - 1).fill('---');
  const core = `  o${segments.join('')}o`;
  const labels = rootToTip.map((v) => shortLabel(v));
  const labelLine = `  ${labels.join('   ')}`;
  return [core, labelLine];
}

/** Branch rows whose tip matches this revision (named pointers). */
export function branchNamesForTip(
  tipVersionId: string,
  branches: Array<{ name: string; tip_version_id: string }>
): string[] {
  return branches.filter((b) => b.tip_version_id === tipVersionId).map((b) => b.name);
}
