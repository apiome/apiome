export const UI_STUDIO_ROUTES = {
  root: '/ade/studio',
  editor: '/ade/studio/editor',
  paths: '/ade/studio/paths',
  code: '/ade/studio/code',
  /** The unified workspace; redirects to the Studio's `/workspace` like its siblings. */
  workspace: '/ade/studio/workspace',
} as const;

/**
 * The workspace's lens query parameter (`?lens=schemas|paths|combined`), which the
 * Studio reads on landing. Named here so a link built in this app cannot misspell it.
 */
export const STUDIO_WORKSPACE_LENS_PARAM = 'lens';

export const STUDIO_APP_ROUTES = {
  root: '/',
  editor: '/editor',
  paths: '/paths',
  code: '/code',
  /** The unified canvas; comment deep links (COL-1.2 format, used by COL-1.3 #4515) land here. */
  workspace: '/workspace',
  /** The read-only preview of one catalog item (MFI-23.12, #4021): `/catalog/{itemId}`. */
  catalog: '/catalog',
} as const;
