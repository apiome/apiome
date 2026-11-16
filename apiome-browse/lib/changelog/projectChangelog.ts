/**
 * The public per-API changelog page model (PCX-2.1, #5896).
 *
 * Framework-free so the `/tenant/{t}/{p}/changelog` page stays a thin renderer: this module turns
 * the rows from `getPublicChangelogsForProject` (newest publish first) plus the page's shareable
 * filters (`?severity=`, `?pathGroup=`, `?since=`) into one display-ready section per published
 * version. Entries keep the stored CTG-1.3 order (breaking → non-breaking → docs-only, then path
 * group) via `groupChangelogEntries` — never re-sorted — and every non-ready row is turned into an
 * explicit state so a version never renders as an empty section.
 */

import { groupChangelogEntries, type SeveritySection } from './group';
import type { ChangelogEntry, PublicVersionChangelogRow, Severity } from './types';

/** The severities a `?severity=` filter accepts, worst first. */
export const CHANGELOG_SEVERITIES: readonly Severity[] = ['breaking', 'non-breaking', 'docs-only'];

/** The page's server-side filters, parsed from the query string. Absent means "no filter". */
export interface ChangelogFilters {
  /** Only entries of this severity. */
  severity?: Severity;
  /** Only entries whose `pathGroup` equals this value (e.g. `/paths/~1pets`). */
  pathGroup?: string;
  /** Only versions published after this version label (exclusive). */
  since?: string;
}

/**
 * How a version's section renders:
 * - `ready` — classified; entries (possibly none) are listed.
 * - `initial` — first publication, no baseline to diff against.
 * - `failed` — classification failed; readers are pointed at the plain diff.
 * - `pending` — published but not classified yet.
 */
export type ChangelogSectionState = 'ready' | 'initial' | 'failed' | 'pending';

/** Per-severity tallies of the entries a section shows. */
export interface ShownCounts {
  breaking: number;
  'non-breaking': number;
  'docs-only': number;
  total: number;
}

/** One rendered entry: the stored entry plus its permalink anchor and compare deep-link. */
export interface ChangelogPageEntry {
  entry: ChangelogEntry;
  /** Stable, unique-on-the-page `id` for the entry's permalink (`#<anchor>`). */
  anchor: string;
  /** `compare?v1=&v2=&focus=` link (relative to the project), or null without a baseline. */
  compareHref: string | null;
}

/** One path group of a severity section, with anchored entries. */
export interface ChangelogPageGroup {
  pathGroup: string;
  entries: ChangelogPageEntry[];
}

/** One severity section of a version, in CTG order. */
export interface ChangelogPageSeverity {
  severity: Severity;
  count: number;
  groups: ChangelogPageGroup[];
}

/** One published version's section on the changelog page. */
export interface ChangelogPageSection {
  versionLabel: string;
  /** The version the changes are measured against (payload `fromVersion`, else the row's baseline). */
  baselineLabel: string | null;
  publishedAt: string | null;
  state: ChangelogSectionState;
  /** Stable `id` of the version heading (`#<anchor>`). */
  anchor: string;
  /** The stored totals (`counts` from the payload) — null unless `state === 'ready'`. */
  storedCounts: ShownCounts | null;
  /** Tallies of the entries shown after filtering. */
  shownCounts: ShownCounts;
  severities: ChangelogPageSeverity[];
}

/** The whole page model. */
export interface ProjectChangelogModel {
  sections: ChangelogPageSection[];
  /** Every path group across all classified versions (sorted), for the path-group filter. */
  pathGroups: string[];
  /** The `since` filter named a version that is not on this project (all versions are shown). */
  sinceNotFound: boolean;
  /** Any filter is active. */
  filtered: boolean;
}

/** Read one query-string value (first value when repeated), trimmed; undefined when blank. */
function firstParam(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed ? trimmed : undefined;
}

/**
 * Parse the page's filters from Next.js `searchParams`. Unknown severities are dropped (the page
 * then shows every severity) rather than producing an empty page.
 *
 * @param params - The page's resolved `searchParams`.
 * @returns The recognised filters.
 */
export function parseChangelogFilters(
  params: Record<string, string | string[] | undefined>
): ChangelogFilters {
  const filters: ChangelogFilters = {};
  const severity = firstParam(params.severity);
  if (severity && (CHANGELOG_SEVERITIES as string[]).includes(severity)) {
    filters.severity = severity as Severity;
  }
  const pathGroup = firstParam(params.pathGroup);
  if (pathGroup) filters.pathGroup = pathGroup;
  const since = firstParam(params.since);
  if (since) filters.since = since;
  return filters;
}

/**
 * Serialize filters back to a query string (`?severity=…&pathGroup=…&since=…`), omitting absent
 * ones, so the page, the Markdown link and the filter chips all share one URL shape.
 *
 * @param filters - Filters to encode.
 * @returns `''` when no filter is set, else a string starting with `?`.
 */
export function changelogFilterQuery(filters: ChangelogFilters): string {
  const qs = new URLSearchParams();
  if (filters.severity) qs.set('severity', filters.severity);
  if (filters.pathGroup) qs.set('pathGroup', filters.pathGroup);
  if (filters.since) qs.set('since', filters.since);
  const s = qs.toString();
  return s ? `?${s}` : '';
}

/**
 * The compare deep-link for one change: `/tenant/{t}/{p}/compare?v1=<base>&v2=<head>&focus=<ptr>`.
 * Shared by the version Changes tab and the project changelog page.
 *
 * @param tenantSlug - Tenant slug.
 * @param projectSlug - Project slug.
 * @param baseline - The older version label, or null when there is nothing to diff against.
 * @param version - The newer version label.
 * @param pointer - JSON Pointer the compare view scrolls to.
 * @returns The link, or null when `baseline` is missing.
 */
export function compareFocusHref(
  tenantSlug: string,
  projectSlug: string,
  baseline: string | null | undefined,
  version: string,
  pointer: string
): string | null {
  if (!baseline) return null;
  return (
    `/tenant/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(projectSlug)}/compare` +
    `?v1=${encodeURIComponent(baseline)}&v2=${encodeURIComponent(version)}&focus=${encodeURIComponent(pointer)}`
  );
}

/** Lower-case a label into an `id`-safe slug (`1.5.0-rc.1` → `1-5-0-rc-1`). */
function slugify(raw: string): string {
  const slug = raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'x';
}

/** 32-bit FNV-1a hash as 8 hex characters — short, deterministic, dependency-free. */
function fnv1a(text: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

/**
 * The anchor `id` of a version's section: `v-<slug>` (e.g. `v-1-5-0`).
 *
 * @param versionLabel - The version label.
 * @returns The anchor id.
 */
export function versionAnchor(versionLabel: string): string {
  return `v-${slugify(versionLabel)}`;
}

/**
 * The permalink anchor of one entry: `v-<version slug>-<hash>`, where the hash covers the entry's
 * pointer, rule and change kind — stable across renders and filters, so a shared `#anchor` keeps
 * pointing at the same change. The caller de-duplicates true collisions (see `buildProjectChangelog`).
 *
 * @param versionLabel - The version the entry belongs to.
 * @param entry - The changelog entry.
 * @returns The anchor id.
 */
export function entryAnchor(versionLabel: string, entry: ChangelogEntry): string {
  return `${versionAnchor(versionLabel)}-${fnv1a(`${entry.pointer}\u0000${entry.ruleId}\u0000${entry.changeKind}`)}`;
}

/** Zeroed tallies. */
function emptyCounts(): ShownCounts {
  return { breaking: 0, 'non-breaking': 0, 'docs-only': 0, total: 0 };
}

/** Tally grouped sections into per-severity counts. */
function tally(sections: SeveritySection[]): ShownCounts {
  const counts = emptyCounts();
  for (const section of sections) {
    counts[section.severity] += section.count;
    counts.total += section.count;
  }
  return counts;
}

/** The section state a row renders as. */
function sectionState(row: PublicVersionChangelogRow): ChangelogSectionState {
  if (row.status === 'failed') return 'failed';
  if (row.status === 'initial' || row.changelog?.initialPublication) return 'initial';
  if (row.status === 'ready' && row.changelog) return 'ready';
  return 'pending';
}

/** Coerce a row's `publishedAt` to an ISO string (null when missing or invalid). */
function publishedIso(value: string | Date | null): string | null {
  if (value == null) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/**
 * Build the changelog page model from a project's rows (newest publish first) and filters.
 *
 * - `since` keeps the versions above the named one (exclusive); an unknown label keeps them all
 *   and sets `sinceNotFound`.
 * - `severity` / `pathGroup` filter the entries of `ready` sections; non-ready sections keep their
 *   explicit state.
 * - `pathGroups` always lists every path group of the versions in range, so the filter control can
 *   switch groups without clearing first.
 *
 * @param rows - Rows from `getPublicChangelogsForProject`, newest first.
 * @param filters - Parsed filters.
 * @param tenantSlug - Tenant slug (for compare links).
 * @param projectSlug - Project slug (for compare links).
 * @returns The page model.
 */
export function buildProjectChangelog(
  rows: readonly PublicVersionChangelogRow[],
  filters: ChangelogFilters,
  tenantSlug: string,
  projectSlug: string
): ProjectChangelogModel {
  let inRange: readonly PublicVersionChangelogRow[] = rows;
  let sinceNotFound = false;
  if (filters.since) {
    const idx = rows.findIndex((r) => r.versionLabel === filters.since);
    if (idx === -1) {
      sinceNotFound = true;
    } else {
      inRange = rows.slice(0, idx);
    }
  }

  const pathGroupSet = new Set<string>();
  const usedAnchors = new Set<string>();
  const sections: ChangelogPageSection[] = [];

  for (const row of inRange) {
    const state = sectionState(row);
    const payload = state === 'ready' ? row.changelog : null;
    const allEntries = payload?.entries ?? [];
    for (const e of allEntries) pathGroupSet.add(e.pathGroup);

    const kept = allEntries.filter(
      (e) =>
        (!filters.severity || e.severity === filters.severity) &&
        (!filters.pathGroup || e.pathGroup === filters.pathGroup)
    );
    const grouped = groupChangelogEntries(kept);
    const baselineLabel = payload?.fromVersion ?? row.baselineVersionLabel ?? null;

    const severities: ChangelogPageSeverity[] = grouped.map((section) => ({
      severity: section.severity,
      count: section.count,
      groups: section.groups.map((group) => ({
        pathGroup: group.pathGroup,
        entries: group.entries.map((entry) => {
          // Anchors come from the full entry identity; a true duplicate gets a numeric suffix.
          const base = entryAnchor(row.versionLabel, entry);
          let anchor = base;
          for (let n = 2; usedAnchors.has(anchor); n++) anchor = `${base}-${n}`;
          usedAnchors.add(anchor);
          return {
            entry,
            anchor,
            compareHref: compareFocusHref(
              tenantSlug,
              projectSlug,
              baselineLabel,
              row.versionLabel,
              entry.pointer
            ),
          };
        }),
      })),
    }));

    const stored = payload?.counts;
    sections.push({
      versionLabel: row.versionLabel,
      baselineLabel,
      publishedAt: publishedIso(row.publishedAt),
      state,
      anchor: versionAnchor(row.versionLabel),
      storedCounts: stored
        ? {
            breaking: stored.breaking ?? 0,
            'non-breaking': stored['non-breaking'] ?? 0,
            'docs-only': stored['docs-only'] ?? 0,
            total: stored.total ?? allEntries.length,
          }
        : null,
      shownCounts: tally(grouped),
      severities,
    });
  }

  return {
    sections,
    pathGroups: [...pathGroupSet].sort(),
    sinceNotFound,
    filtered: Boolean(filters.severity || filters.pathGroup || filters.since),
  };
}

/**
 * The explicit one-line note a non-ready (or empty) section renders instead of entries — never an
 * empty section.
 *
 * @param section - The section.
 * @param filtered - Whether any page filter is active (changes the empty-ready wording).
 * @returns The note, or null when the section has entries to list.
 */
export function sectionNote(section: ChangelogPageSection, filtered: boolean): string | null {
  switch (section.state) {
    case 'failed':
      return `Classification failed for ${section.versionLabel} — plain diff only.`;
    case 'initial':
      return 'Initial publication — no prior baseline to compare against.';
    case 'pending':
      return `Changes for ${section.versionLabel} are pending classification.`;
    case 'ready':
      if (section.shownCounts.total > 0) return null;
      return filtered && (section.storedCounts?.total ?? 0) > 0
        ? 'No changes in this version match the filters.'
        : 'No changes detected.';
  }
}
