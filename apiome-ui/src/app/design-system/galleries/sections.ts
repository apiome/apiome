/**
 * The contents of the `/design-system` route (HIVE-10.5, #5341).
 *
 * One entry per anchored section the page draws, in page order. The route builds its contents
 * list from this, and `tests/design-system-gallery.test.ts` checks that every entry is a real
 * `id` in its gallery — so a section cannot be renamed out from under its link.
 */

/** One anchored section of the page. */
export interface GallerySection {
  /** The element `id` the contents list links to. */
  id: string;
  /** What the contents list calls it. */
  label: string;
}

/** The Hive primitive sections, in the order `HiveGallery` draws them. */
export const HIVE_GALLERY_SECTIONS: readonly GallerySection[] = [
  { id: 'buttons', label: 'Buttons' },
  { id: 'forms', label: 'Forms' },
  { id: 'badges', label: 'Badges & status' },
  { id: 'status-vocabulary', label: 'Status vocabulary' },
  { id: 'cards', label: 'Cards' },
  { id: 'tabs', label: 'Tabs' },
  { id: 'segmented', label: 'Segmented' },
  { id: 'avatars', label: 'Avatars' },
  { id: 'tables', label: 'Tables' },
  { id: 'overlays', label: 'Overlays & banners' },
  { id: 'dialogs', label: 'Confirms & prompts' },
  { id: 'feedback', label: 'Feedback' },
  { id: 'metrics', label: 'Metrics' },
];

/** The supporting primitive sections, in the order `SupportingGallery` draws them. */
export const SUPPORTING_GALLERY_SECTIONS: readonly GallerySection[] = [
  { id: 'catalog-pills', label: 'Catalog pills' },
  { id: 'structure', label: 'Labels, steps & disclosure' },
  { id: 'markdown', label: 'Markdown' },
  { id: 'modals-toasts', label: 'Legacy modal & toasts' },
  { id: 'loading-shapes', label: 'Loading shapes' },
  { id: 'live-region', label: 'Live region' },
];

/** The anchor of the MCP primitives section the route mounts `McpGallery` under. */
export const MCP_GALLERY_SECTION: GallerySection = { id: 'mcp', label: 'MCP primitives' };

/**
 * The pattern galleries that keep their own route, because each one takes over the page
 * (a full page header, the global command palette, the shortcut sheet) and cannot sit
 * inside another page as a section.
 */
export const PATTERN_GALLERIES: readonly { href: string; label: string; description: string }[] = [
  {
    href: '/design-system/page-header',
    label: 'Page header',
    description: 'Page, PageHeader and PageBody at page scale, in the app’s three shapes.',
  },
  {
    href: '/design-system/command-palette',
    label: 'Command palette',
    description: 'The real ⌘K palette, opened over the real stylesheet.',
  },
  {
    href: '/design-system/shortcuts',
    label: 'Shortcut sheet',
    description: 'The generated shortcut sheet, with registrations you can toggle.',
  },
];
