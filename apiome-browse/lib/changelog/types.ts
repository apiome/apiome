/**
 * Types for the persisted publish changelog (`ctg.changelog.v1`, CTG-3.1 #4475) as read from
 * `apiome.version_changelogs` — the shapes the Changes tab, compare badges, and feeds consume
 * (CTG-3.2, #4476). Keys are camelCase exactly as the REST classifier serializes them.
 */

/** Change severity taxonomy, worst first. */
export type Severity = 'breaking' | 'non-breaking' | 'docs-only';

/** Classification lifecycle of a stored changelog row. */
export type ChangelogStatus = 'ready' | 'initial' | 'failed';

/** One ordered, display-ready change in a `ctg.changelog.v1` payload. */
export interface ChangelogEntry {
  severity: Severity;
  /** Grouping key derived from the pointer (e.g. `/paths/~1pets` or `/components/schemas/Pet`). */
  pathGroup: string;
  /** JSON Pointer to the changed node. */
  pointer: string;
  ruleId: string;
  changeKind: string;
  summary: string;
  before?: unknown;
  after?: unknown;
  /** True when the classifier failed safe (treated as breaking). */
  unclassified?: boolean;
  fromVersion?: string | null;
  toVersion?: string | null;
}

/** Tallies per severity plus the fail-safe bucket. */
export interface ChangelogCounts {
  breaking: number;
  'non-breaking': number;
  'docs-only': number;
  unclassified: number;
  total: number;
}

/** The full stored `ctg.changelog.v1` payload (`changelog_json`). */
export interface ChangelogPayload {
  schemaVersion: string;
  fromVersion: string | null;
  toVersion: string | null;
  counts: ChangelogCounts;
  maxSeverity: Severity | null;
  /** Entries pre-ordered breaking → non-breaking → docs-only, then pathGroup, then pointer. */
  entries: ChangelogEntry[];
  /** Present (true) on first-publication rows that have no baseline to diff against. */
  initialPublication?: true;
}

/**
 * One public version's changelog row as returned by the DB helpers
 * (`getPublicVersionChangelog` / `getPublicChangelogsForProject`). `status` and `changelog` are
 * null when the version is public but no classification row exists yet ("pending"). The private
 * `error` column is deliberately never part of this shape.
 */
export interface PublicVersionChangelogRow {
  publishedRevisionId: string;
  versionLabel: string;
  /** pg returns timestamptz as Date server-side; serialized to a string across the RSC boundary. */
  publishedAt: string | Date | null;
  baselineVersionLabel: string | null;
  maxSeverity: Severity | null;
  status: ChangelogStatus | null;
  changelog: ChangelogPayload | null;
}
