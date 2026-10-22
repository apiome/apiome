/**
 * Export studio's two tabs (HIVE-12.2, #5609) — the pure half.
 *
 * `docs/mockups/proposals/rail-compact.html` callout 4: SDK settings left the rail and became
 * the **SDK & branding** tab of Export studio, because both decide how a published version
 * leaves the platform. The tabs are a route strip over one route: `?tab=sdk` selects SDK &
 * branding, and its absence is the export itself. `/ade/dashboard/sdk-settings` redirects to
 * the `sdk` tab.
 *
 * A tab link keeps every other query parameter, so leaving the export for SDK & branding and
 * coming back returns to the same source, target, options and step.
 */

/** The query parameter that selects a tab. */
export const EXPORT_STUDIO_TAB_PARAM = 'tab';

/** One of Export studio's tabs. */
export type ExportStudioTabId = 'export' | 'sdk';

/** A tab of the strip. */
export interface ExportStudioTab {
  /** Stable id — the `?tab=` value (none for `export`) and the test-id suffix. */
  id: ExportStudioTabId;
  /** The label, in sentence case. */
  label: string;
  /** The `lib/feature-release.ts` id that gates the tab. */
  feature: string;
}

/** The tabs, in strip order. */
export const EXPORT_STUDIO_TABS: readonly ExportStudioTab[] = [
  { id: 'export', label: 'Export', feature: 'export-studio' },
  { id: 'sdk', label: 'SDK & branding', feature: 'sdk-settings' },
];

/**
 * Which tab a query string selects.
 *
 * @param params The route's search parameters (anything with a `get`).
 * @returns `sdk` for `?tab=sdk`; `export` for no `tab`, or one this build does not know.
 */
export function exportStudioTabFromParams(
  params: Pick<URLSearchParams, 'get'> | null | undefined
): ExportStudioTabId {
  return params?.get(EXPORT_STUDIO_TAB_PARAM) === 'sdk' ? 'sdk' : 'export';
}

/**
 * The link to one tab, keeping the rest of the query string.
 *
 * @param pathname The Export studio route.
 * @param params The current search parameters; not modified.
 * @param tab The tab to link to.
 * @returns `pathname` with `?tab=sdk` set for SDK & branding or removed for Export.
 */
export function exportStudioTabHref(
  pathname: string,
  params: URLSearchParams | null | undefined,
  tab: ExportStudioTabId
): string {
  const next = new URLSearchParams(params?.toString() ?? '');
  if (tab === 'export') next.delete(EXPORT_STUDIO_TAB_PARAM);
  else next.set(EXPORT_STUDIO_TAB_PARAM, tab);
  const query = next.toString();
  return query ? `${pathname}?${query}` : pathname;
}
