/**
 * Stored classified version changelogs (`ctg.changelog.v1`, CTG-3.2 #4476).
 *
 * Types and pure helpers over the publish-time classification persisted by
 * CTG-3.1 and served via `/api/versions/[versionId]/changelog` and
 * `/api/projects/[projectId]/changelogs`. Rendering lives in
 * `VersionChangesPanel`; everything here is framework-free and unit-tested.
 */

/** Severity classes emitted by the CTG taxonomy (worst first). */
export type ChangelogSeverity = 'breaking' | 'non-breaking' | 'docs-only';

/** Display order: breaking first (mirrors the CTG-1.3 changelog ordering). */
export const SEVERITY_ORDER: readonly ChangelogSeverity[] = [
  'breaking',
  'non-breaking',
  'docs-only',
];

/** One display-ready change from a `ctg.changelog.v1` payload. */
export interface ChangelogEntry {
  severity: ChangelogSeverity;
  pathGroup: string;
  pointer: string;
  ruleId: string;
  changeKind: string;
  summary: string;
  before?: unknown;
  after?: unknown;
  unclassified?: boolean;
  fromVersion?: string | null;
  toVersion?: string | null;
}

/** The stored `ctg.changelog.v1` payload (or initial-publication marker). */
export interface ChangelogPayload {
  schemaVersion: string;
  fromVersion?: string | null;
  toVersion?: string | null;
  counts?: Record<string, number>;
  maxSeverity?: ChangelogSeverity | null;
  entries?: ChangelogEntry[];
  initialPublication?: boolean;
}

/** Full stored changelog for one published revision (`GET …/changelog`). */
export interface VersionChangelog {
  publishedRevisionId: string;
  baselineRevisionId: string | null;
  versionLabel: string | null;
  baselineVersionLabel: string | null;
  publishedAt: string | null;
  status: 'ready' | 'initial' | 'failed';
  maxSeverity: ChangelogSeverity | null;
  error: string | null;
  changelog: ChangelogPayload | null;
}

/** Summary row for one published revision (`GET …/changelogs`). */
export interface VersionChangelogSummary {
  publishedRevisionId: string;
  versionLabel: string | null;
  publishedAt: string | null;
  baselineRevisionId: string | null;
  baselineVersionLabel: string | null;
  /** `null` when classification is pending (no stored row yet). */
  status: 'ready' | 'initial' | 'failed' | null;
  maxSeverity: ChangelogSeverity | null;
  counts: Record<string, number> | null;
}

/** Entries for one `pathGroup`, in stored order. */
export interface ChangelogPathGroup {
  pathGroup: string;
  entries: ChangelogEntry[];
}

/** All entries of one severity, grouped by `pathGroup`, in stored order. */
export interface ChangelogSeveritySection {
  severity: ChangelogSeverity;
  entries: ChangelogEntry[];
  groups: ChangelogPathGroup[];
}

/** Human badge label per severity. */
export function severityLabel(severity: ChangelogSeverity): string {
  switch (severity) {
    case 'breaking':
      return 'Breaking';
    case 'non-breaking':
      return 'Non-breaking';
    case 'docs-only':
      return 'Docs-only';
  }
}

/** `Badge` component variant per severity (error = red, warning = amber). */
export function severityBadgeVariant(
  severity: ChangelogSeverity,
): 'error' | 'warning' | 'secondary' {
  switch (severity) {
    case 'breaking':
      return 'error';
    case 'non-breaking':
      return 'warning';
    case 'docs-only':
      return 'secondary';
  }
}

/**
 * Group changelog entries into severity sections (breaking first), each grouped
 * by `pathGroup`. Entry order within a group is preserved from the stored
 * payload, which is already deterministic (severity → pathGroup → pointer).
 * Entries with unknown severities are coerced to `docs-only` (fail-safe: the
 * backend marks classifier failures `unclassified` under a known severity).
 */
export function groupChangelogEntries(
  entries: readonly ChangelogEntry[] | undefined | null,
): ChangelogSeveritySection[] {
  const bySeverity = new Map<ChangelogSeverity, ChangelogEntry[]>();
  for (const entry of entries ?? []) {
    const severity: ChangelogSeverity = SEVERITY_ORDER.includes(entry.severity)
      ? entry.severity
      : 'docs-only';
    const bucket = bySeverity.get(severity);
    if (bucket) {
      bucket.push(entry);
    } else {
      bySeverity.set(severity, [entry]);
    }
  }

  const sections: ChangelogSeveritySection[] = [];
  for (const severity of SEVERITY_ORDER) {
    const severityEntries = bySeverity.get(severity);
    if (!severityEntries || severityEntries.length === 0) {
      continue;
    }
    const groups: ChangelogPathGroup[] = [];
    const groupIndex = new Map<string, ChangelogPathGroup>();
    for (const entry of severityEntries) {
      const key = entry.pathGroup || '(other)';
      let group = groupIndex.get(key);
      if (!group) {
        group = { pathGroup: key, entries: [] };
        groupIndex.set(key, group);
        groups.push(group);
      }
      group.entries.push(entry);
    }
    sections.push({ severity, entries: severityEntries, groups });
  }
  return sections;
}

/**
 * Map a changelog JSON Pointer to the `stableId` used by the compare dialog's
 * class-level diff rows (the OpenAPI component name), or `null` when the
 * pointer does not target `components/schemas` (e.g. `paths` changes, which
 * only appear in the text diff).
 *
 * Example: `/components/schemas/Pet/properties/name` → `Pet`.
 */
export function stableIdForPointer(pointer: string): string | null {
  const segments = decodeJsonPointer(pointer);
  if (segments.length >= 3 && segments[0] === 'components' && segments[1] === 'schemas') {
    return segments[2] || null;
  }
  return null;
}

/**
 * Decode an RFC 6901 JSON Pointer into unescaped segments
 * (`~1` → `/`, `~0` → `~`). Returns `[]` for the root pointer.
 */
export function decodeJsonPointer(pointer: string): string[] {
  if (!pointer || pointer === '/') {
    return [];
  }
  const raw = pointer.startsWith('/') ? pointer.slice(1) : pointer;
  return raw.split('/').map((segment) => segment.replace(/~1/g, '/').replace(/~0/g, '~'));
}

/**
 * The set of class-diff `stableId`s that have at least one stored breaking
 * entry — used to badge compare-dialog schema rows from the stored
 * classification.
 */
export function breakingStableIds(
  entries: readonly ChangelogEntry[] | undefined | null,
): Set<string> {
  const ids = new Set<string>();
  for (const entry of entries ?? []) {
    if (entry.severity !== 'breaking') {
      continue;
    }
    const stableId = stableIdForPointer(entry.pointer);
    if (stableId) {
      ids.add(stableId);
    }
  }
  return ids;
}

/**
 * True when a stored changelog classifies exactly the compared pair, i.e. the
 * stored baseline is the revision shown on the left of the diff. Badges must
 * only be shown for the pair the classification was computed for.
 */
export function changelogMatchesComparedPair(
  changelog: Pick<VersionChangelog, 'baselineRevisionId' | 'publishedRevisionId'> | null,
  baseRevisionId: string | null | undefined,
  headRevisionId: string | null | undefined,
): boolean {
  if (!changelog || !baseRevisionId || !headRevisionId) {
    return false;
  }
  return (
    changelog.publishedRevisionId === headRevisionId &&
    changelog.baselineRevisionId === baseRevisionId
  );
}

/**
 * Short counts summary for badges/tab labels, e.g. `1 breaking · 2 non-breaking`.
 * Returns `null` when there is nothing countable.
 */
export function countsSummary(counts: Record<string, number> | null | undefined): string | null {
  if (!counts) {
    return null;
  }
  const parts: string[] = [];
  for (const severity of SEVERITY_ORDER) {
    const count = counts[severity];
    if (typeof count === 'number' && count > 0) {
      parts.push(`${count} ${severity}`);
    }
  }
  return parts.length ? parts.join(' · ') : null;
}
