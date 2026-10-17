/**
 * The rules behind the Versions table's one toolbar (HIVE-11.4, #5600).
 *
 * Authority: `docs/mockups/proposals/versions-status-strip.html` callout **5** — one
 * `.table-toolbar`: search · lifecycle · *Any time ▾* · *All authors ▾* · state chips · sort.
 * The standalone *Timeline* card (HIVE-6.2) is gone; its four filters live here now.
 *
 * Everything in this module is pure, so `tests/versions-toolbar-model.test.ts` can pin it
 * without a router or a DOM:
 *
 *   • {@link VERSIONS_TABLE_FILTERS} — the screen's URL vocabulary, read and written by
 *     `useDataTableUrlState`. The history params are named after the REST revisions list's
 *     own (`q`, `creatorId`, `createdAfter`, `createdBefore`, `lifecycle`), so a toolbar
 *     link and an API call spell a filter the same way.
 *   • {@link versionsDatePresetRange} — the three quick ranges in the date popover.
 *   • {@link versionsDateRangeLabel} / {@link versionsAuthorLabel} — the two trigger labels.
 */

import {
  defineTableFilters,
  textFilter,
  type TableFilters,
} from '@/app/components/ui/dataTableUrlState';

import { VERSION_LIFECYCLES, type VersionFacet } from './versionsModel';

/** One author the toolbar's author menu offers. */
export interface VersionAuthorOption {
  /** The creator id the filter matches on. */
  id: string;
  /** The label — name, else email, else the id. */
  label: string;
}

/**
 * The Versions table's filters, keyed by the query param each is written to.
 *
 * - `q` — the search box (message, changelog, commit body, commit author).
 * - `creatorId` — the author menu.
 * - `createdAfter` / `createdBefore` — the date popover, as `YYYY-MM-DD`, both inclusive.
 * - `lifecycle` — the lifecycle select; the one filter REST applies server-side.
 * - `state` — the Drafts / Published chip; *All* is the absent default.
 * - `tag` — the history select, a tag id ("revisions reachable from this tag").
 */
export const VERSIONS_TABLE_FILTERS = defineTableFilters({
  q: textFilter(),
  creatorId: textFilter(),
  createdAfter: textFilter(),
  createdBefore: textFilter(),
  lifecycle: textFilter(VERSION_LIFECYCLES),
  state: textFilter(['drafts', 'published']),
  tag: textFilter(),
});

/** The Versions table's filter state, as `useDataTableUrlState` hands it back. */
export type VersionsTableFilters = TableFilters<typeof VERSIONS_TABLE_FILTERS.fields>;

/**
 * The filters a project switch clears.
 *
 * The search, author, dates, tag and lifecycle all name things that belong to one project's
 * history, so they do not carry over to the next; the Drafts / Published chip is a way of
 * reading *any* table and stays put — the same split the page made before HIVE-11.4.
 */
export const VERSIONS_PROJECT_SCOPED_FILTERS = [
  'q',
  'creatorId',
  'createdAfter',
  'createdBefore',
  'lifecycle',
  'tag',
] as const satisfies readonly (keyof VersionsTableFilters)[];

/**
 * The quick chip the `state` param names.
 *
 * @param state The `state` filter value (`''`, `'drafts'` or `'published'`).
 * @returns The facet — `'all'` when the param is absent.
 */
export function versionFacetFromState(state: string): VersionFacet {
  return state === 'drafts' || state === 'published' ? state : 'all';
}

/**
 * The `state` param a quick chip writes.
 *
 * @param facet The chip that was pressed.
 * @returns `''` for *All*, so the unfiltered table keeps a bare URL.
 */
export function stateFromVersionFacet(facet: VersionFacet): string {
  return facet === 'all' ? '' : facet;
}

// ---------------------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------------------

/** The quick ranges the date popover offers under its two inputs. */
export const VERSIONS_DATE_PRESETS = ['last7', 'last30', 'quarter'] as const;

/** One quick range. */
export type VersionsDatePreset = (typeof VERSIONS_DATE_PRESETS)[number];

/** The chip label for each quick range, as the mockup prints it. */
export const VERSIONS_DATE_PRESET_LABEL: Record<VersionsDatePreset, string> = {
  last7: 'Last 7 days',
  last30: 'Last 30 days',
  quarter: 'This quarter',
};

/** A from / to pair as the inputs and the URL hold it — `YYYY-MM-DD`, or `''` for open. */
export interface VersionsDateRange {
  from: string;
  to: string;
}

/**
 * A local calendar day as `YYYY-MM-DD` — the value an `<input type="date">` holds.
 *
 * Local rather than UTC because the filter compares against local midnight
 * (`revisionMatchesHistoryFilters`), and "today" is the reader's today.
 *
 * @param date The day.
 * @returns The ISO calendar date.
 */
export function isoDay(date: Date): string {
  const y = String(date.getFullYear()).padStart(4, '0');
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * The from / to pair a quick range stands for.
 *
 * "Last 7 days" counts today, so it starts six days back; "This quarter" runs from the first
 * day of the calendar quarter to today. Every range ends today — a revision cannot be dated
 * in the future, and an open `to` would make the range read differently tomorrow.
 *
 * @param preset The quick range.
 * @param now The moment to measure from (the caller's clock; injectable for tests).
 * @returns The inclusive range.
 */
export function versionsDatePresetRange(preset: VersionsDatePreset, now: Date): VersionsDateRange {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let from: Date;
  switch (preset) {
    case 'last7':
      from = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6);
      break;
    case 'last30':
      from = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 29);
      break;
    case 'quarter':
      from = new Date(today.getFullYear(), Math.floor(today.getMonth() / 3) * 3, 1);
      break;
  }
  return { from: isoDay(from), to: isoDay(today) };
}

/**
 * Which quick range a from / to pair is exactly, if any — so its chip can read as pressed.
 *
 * @param range The pair.
 * @param now The moment the presets are measured from.
 * @returns The matching preset, or `null`.
 */
export function versionsDatePresetFor(range: VersionsDateRange, now: Date): VersionsDatePreset | null {
  for (const preset of VERSIONS_DATE_PRESETS) {
    const candidate = versionsDatePresetRange(preset, now);
    if (candidate.from === range.from && candidate.to === range.to) return preset;
  }
  return null;
}

/**
 * A `YYYY-MM-DD` value as a short local date for the trigger (`Oct 3, 2026`).
 *
 * @param iso The calendar date.
 * @returns The short label, or the raw value when it is not a calendar date.
 */
function shortDay(iso: string): string {
  const parts = iso.split('-').map((part) => parseInt(part, 10));
  if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) return iso;
  const [y, m, d] = parts;
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * The date trigger's label.
 *
 * *Any time* with nothing set; the preset's own name when the pair is exactly one; otherwise
 * the range in words — *Since Oct 3, 2026*, *Until …*, or *Oct 3, 2026 – Oct 9, 2026*.
 *
 * @param range The applied pair.
 * @param now The moment the presets are measured from.
 * @returns The label.
 */
export function versionsDateRangeLabel(range: VersionsDateRange, now: Date): string {
  if (!range.from && !range.to) return 'Any time';
  const preset = versionsDatePresetFor(range, now);
  if (preset) return VERSIONS_DATE_PRESET_LABEL[preset];
  if (range.from && range.to) return `${shortDay(range.from)} – ${shortDay(range.to)}`;
  return range.from ? `Since ${shortDay(range.from)}` : `Until ${shortDay(range.to)}`;
}

/**
 * Whether a from / to pair can be applied — both open, or `from` on or before `to`.
 *
 * ISO calendar dates compare correctly as strings, which is why the inputs' own values are
 * compared rather than parsed.
 *
 * @param range The pair being drafted.
 * @returns `true` when it is a real range.
 */
export function isVersionsDateRangeValid(range: VersionsDateRange): boolean {
  return !range.from || !range.to || range.from <= range.to;
}

// ---------------------------------------------------------------------------------------
// Authors
// ---------------------------------------------------------------------------------------

/**
 * The author trigger's label.
 *
 * @param authorId The applied creator id, or `''`.
 * @param options The authors in the loaded list.
 * @returns *All authors*, the author's label, or — for an id the list does not hold yet (a
 *   shared link read before the revisions land) — *1 author*, which is still true.
 */
export function versionsAuthorLabel(authorId: string, options: readonly VersionAuthorOption[]): string {
  if (!authorId) return 'All authors';
  return options.find((option) => option.id === authorId)?.label ?? '1 author';
}
