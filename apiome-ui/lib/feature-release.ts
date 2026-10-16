/* ==========================================================================
   Feature release gate — the MVP focus on Catalog and Projects
   --------------------------------------------------------------------------
   Until Catalog and Projects are hardened for the MVP, the destinations below
   stay in the code but out of reach: the rail, the command palette and the
   `G`-jumps show them disabled (through `getPlatformNavGroups()`), and their
   routes render a "not available yet" page instead of the feature
   (`UnreleasedFeatureGate`).

   The ids are `PlatformNavItem.id`s, so the navigation model, the route gate
   and the docs backup (`apiome-docs/unreleased/README.md`) all name a feature
   the same way. Releasing one is: delete its id here, restore its docs pages.

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
] as const;

/** One of {@link UNRELEASED_FEATURE_IDS}. */
export type UnreleasedFeatureId = (typeof UNRELEASED_FEATURE_IDS)[number];

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

/**
 * Why an unreleased destination is unavailable — tooltip and palette copy.
 *
 * @param label - The destination's label.
 * @returns One sentence naming the destination.
 */
export function unreleasedFeatureReason(label: string): string {
  return `${label} is not available yet.`;
}
