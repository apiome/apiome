export const UI_STUDIO_ROUTES = {
  root: '/ade/studio',
  editor: '/ade/studio/editor',
  paths: '/ade/studio/paths',
  code: '/ade/studio/code',
} as const;

/**
 * Authoring destinations (UXE-1.1).
 *
 * Authoring is a commercial suite product, so it is implemented and served by
 * the studio app, not here. These are studio-surface paths: the main app only
 * links to them, gated by the `scribe`, `slate` and `hosted` license flags, and
 * never renders an Authoring route itself.
 */
export const STUDIO_AUTHORING_ROUTES = {
  root: '/authoring',
  scribe: '/authoring/scribe',
  slate: '/authoring/slate',
  releases: '/authoring/releases',
  insights: '/authoring/insights',
} as const;

export const STUDIO_APP_ROUTES = {
  root: '/',
  editor: '/editor',
  paths: '/paths',
  code: '/code',
} as const;
