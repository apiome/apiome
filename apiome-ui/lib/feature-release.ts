/* ==========================================================================
   Feature release gate — the MVP focus on Catalog and Projects
   --------------------------------------------------------------------------
   Until Catalog and Projects are hardened for the MVP, the destinations below
   stay in the code but out of reach: the rail, the command palette and the
   `G`-jumps leave them out (through `getPlatformNavGroups()`), and their
   routes render a "not available yet" page instead of the feature
   (`UnreleasedFeatureGate`).

   The ids are `PlatformNavItem.id`s, so the navigation model, the route gate
   and the docs backup (`apiome-docs/unreleased/README.md`) all name a feature
   the same way. Releasing one is: delete its id here, restore its docs pages.
   One id names a feature with no rail item of its own, embedded in Projects:
   `consumers` (a project's consumer contract registry, CTG-4.1).

   A gated feature is hidden where it is embedded too: `teams` takes the owner
   column, filter and bulk action off Projects, Catalog and Published;
   `dependency-graph` the Dependencies tabs.

   RC7 released every way into the Catalog: `connectors` (gateways and
   registries, with the refresh ledger on Repositories), `schema-registry`
   (the catalog Subjects tab) and `catalog-entities` (agents, models,
   components, the Backstage/Compass import reports and scorecard facts, CDG-5).
   They are still checked with `isFeatureReleased()` where they are embedded,
   which now always answers true for them.

   `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES` re-opens gated features for a build —
   a comma-separated list of ids, or `all` — so developers, the docs screenshot
   run and e2e suites can still reach them. It is inlined at build time, so it
   is read by its literal name.
   ========================================================================== */

/** Destinations that exist in the code but are not released (rail item ids). */
export const UNRELEASED_FEATURE_IDS = [
  'primitives',
  'mcp',
  'export-studio',
  'sdk-settings',
  'style-guides',
  'audit',
  // RC6 scope (docs/RC6_OOE.md): Catalog Discovery Graph and contract-testing
  // surfaces wait for a later release. RC7 released the Catalog's import paths:
  // `connectors`, `schema-registry` and `catalog-entities`.
  'shadow-apis',
  'dependency-graph',
  'teams',
  'consumers',
] as const;

/** One of {@link UNRELEASED_FEATURE_IDS}. */
export type UnreleasedFeatureId = (typeof UNRELEASED_FEATURE_IDS)[number];

/**
 * The unreleased features that have no rail item, with the name and section a
 * gated route shows for them (a rail item's own label and group are used otherwise).
 */
export const EMBEDDED_FEATURES: Readonly<Record<string, { label: string; section: string }>> = {
  consumers: { label: 'Consumer contracts', section: 'Projects' },
};

/** The build-time override that re-opens gated features (`all`, or a comma-separated id list). */
export const PREVIEW_FEATURES_ENV = 'NEXT_PUBLIC_APIOME_PREVIEW_FEATURES';

const UNRELEASED: ReadonlySet<string> = new Set(UNRELEASED_FEATURE_IDS);

/**
 * Parse the preview override into the set of ids it re-opens.
 *
 * @param raw - The variable's value; absent or blank re-opens nothing.
 * @returns `'all'`, or the ids listed (trimmed, empties dropped).
 */
export function parsePreviewFeatures(raw: string | undefined | null): 'all' | ReadonlySet<string> {
  const value = raw?.trim() ?? '';
  if (value.toLowerCase() === 'all') return 'all';
  return new Set(
    value
      .split(',')
      .map((id) => id.trim())
      .filter(Boolean)
  );
}

/**
 * Is the destination with this id released for this build?
 *
 * Anything not named in {@link UNRELEASED_FEATURE_IDS} is released — the gate
 * only ever closes the features it lists.
 *
 * @param id - A `PlatformNavItem.id`.
 * @param previewFeatures - Override value; defaults to the build's
 *   `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES`.
 * @returns True when the destination may be opened.
 */
export function isFeatureReleased(
  id: string,
  previewFeatures: string | undefined | null = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES
): boolean {
  if (!UNRELEASED.has(id)) return true;
  const preview = parsePreviewFeatures(previewFeatures);
  return preview === 'all' || preview.has(id);
}
