export const UI_STUDIO_ROUTES = {
  root: '/ade/studio',
  editor: '/ade/studio/editor',
  paths: '/ade/studio/paths',
  code: '/ade/studio/code',
} as const;

/**
 * Authoring destinations (UXE-1.1). These always live on the main app surface,
 * so the studio surface links to them with an absolute main-app URL.
 */
export const UI_AUTHORING_ROUTES = {
  root: '/ade/authoring',
  scribe: '/ade/authoring/scribe',
  slate: '/ade/authoring/slate',
  releases: '/ade/authoring/releases',
  insights: '/ade/authoring/insights',
  /** Primitive reference gallery (UXE-1.3). Not a suite destination. */
  reference: '/ade/authoring/reference',
} as const;

export const STUDIO_APP_ROUTES = {
  root: '/',
  editor: '/editor',
  paths: '/paths',
  code: '/code',
} as const;
