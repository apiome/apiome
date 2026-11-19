/* ==========================================================================
   Feature release gate
   --------------------------------------------------------------------------
   A destination listed below stays in the code but out of reach: the rail,
   the command palette and the `G`-jumps leave it out (through
   `getPlatformNavGroups()`), and every `isFeatureReleased()` check around the
   places it is embedded hides it.

   The ids are `PlatformNavItem.id`s, so the navigation model and the docs
   backup (`apiome-docs/unreleased/README.md`) name a feature the same way.

   RC8 is about Catalog and Projects, so five features are held back again and
   released one at a time, each when its own GitHub Project is complete (the
   completion checklist, the docs and the demo video in that project). The
   Data browser and Migrations tools left this application: they belong to
   Api-DB, a separate product. To hold a feature back, add its id here, gate
   its route with `UnreleasedFeatureGate` and move its docs page to
   `apiome-docs/unreleased/`; to release it, follow "Restore a feature" in
   that folder's README.

   `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES` re-opens gated features for a build —
   a comma-separated list of ids, or `all` — so developers, the docs screenshot
   run and e2e suites can still reach them. It is inlined at build time, so it
   is read by its literal name.
   ========================================================================== */

/** Destinations that exist in the code but are not released (rail item ids). */
export const UNRELEASED_FEATURE_IDS = [
  // Each id is released by its own "Enable" project: when every item in the project is Done,
  // delete the id here, delete the route's layout.tsx gate and restore its docs page.
  // Planned order: Dependency graph, Schema registry, Connectors, Shadow APIs, Products.
  'dependency-graph', // Enable: Dependency graph — https://github.com/orgs/apiome/projects/127
  'schema-registry', //  Enable: Schema registry   — https://github.com/orgs/apiome/projects/128
  'connectors', //       Enable: Connectors        — https://github.com/orgs/apiome/projects/129
  'shadow-apis', //      Enable: Shadow APIs       — https://github.com/orgs/apiome/projects/130 (needs connectors)
  'products', //         Enable: Products          — https://github.com/orgs/apiome/projects/131
] as const;

/** One of {@link UNRELEASED_FEATURE_IDS}. */
export type UnreleasedFeatureId = (typeof UNRELEASED_FEATURE_IDS)[number];

/**
 * The GitHub Project that tracks each held-back feature to completion. A feature is released
 * (its id removed from {@link UNRELEASED_FEATURE_IDS}) once every item in its project is Done.
 */
export const ENABLE_PROJECTS: Readonly<Record<UnreleasedFeatureId, { label: string; url: string }>> = {
  'dependency-graph': { label: 'Dependency graph', url: 'https://github.com/orgs/apiome/projects/127' },
  'schema-registry': { label: 'Schema registry', url: 'https://github.com/orgs/apiome/projects/128' },
  connectors: { label: 'Connectors', url: 'https://github.com/orgs/apiome/projects/129' },
  'shadow-apis': { label: 'Shadow APIs', url: 'https://github.com/orgs/apiome/projects/130' },
  products: { label: 'Products', url: 'https://github.com/orgs/apiome/projects/131' },
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
