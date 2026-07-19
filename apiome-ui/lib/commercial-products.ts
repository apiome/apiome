import { getMainAppUrl, getStudioAppUrl } from './app-urls';
import type { ExternalLinkEntry, ExternalNavMenuGroup } from './external-links';
import { STUDIO_APP_ROUTES, UI_AUTHORING_ROUTES } from './studio-routes';

/**
 * Feature-flag slugs that map to first-party commercial applications.
 * `designer`/`paths` gate the Design group; `scribe`/`slate`/`hosted` gate the
 * Authoring group (UXE-1.1).
 */
export const COMMERCIAL_PRODUCT_FLAG_NAMES = [
  'designer',
  'paths',
  'scribe',
  'slate',
  'hosted',
] as const;

/** Ordered group headings for the Designer suite dropdown. */
export const SUITE_MENU_GROUPS: ExternalNavMenuGroup[] = [
  { id: 'design', label: 'Design' },
  { id: 'authoring', label: 'Authoring' },
];

export type CommercialProductFlagName = (typeof COMMERCIAL_PRODUCT_FLAG_NAMES)[number];

function isStudioSurface(): boolean {
  return process.env.NEXT_PUBLIC_APP_SURFACE === 'studio';
}

function resolveStudioSurfaceHref(path: string): string {
  if (isStudioSurface()) return path;
  return new URL(path.replace(/^\//, ''), getStudioAppUrl()).toString();
}

function resolveStudioRootHref(): string {
  if (isStudioSurface()) return STUDIO_APP_ROUTES.root;
  return getStudioAppUrl();
}

function resolveStudioEditorHref(): string {
  return resolveStudioSurfaceHref(STUDIO_APP_ROUTES.editor);
}

/**
 * Resolve a main-app path for the current surface: the studio surface needs an
 * absolute main-app URL, the main surface keeps the in-app path.
 */
function resolveMainSurfaceHref(path: string): string {
  if (isStudioSurface()) return `${getMainAppUrl()}${path}`;
  return path;
}

function isAbsoluteHref(href: string): boolean {
  return href.startsWith('http://') || href.startsWith('https://');
}

/**
 * Built-in commercial applications shipped with apiome-ui.
 * Designer Suite visibility is gated by license feature flags (`designer` or `paths`).
 * Developer Suite is always listed on the home grid as coming soon.
 */
export function getBuiltinCommercialProducts(): ExternalLinkEntry[] {
  const suiteHref = resolveStudioRootHref();
  const editorHref = resolveStudioEditorHref();
  const pathsHref = resolveStudioSurfaceHref(STUDIO_APP_ROUTES.paths);
  const authoringHref = (path: string) => resolveMainSurfaceHref(path);

  return [
    {
      id: 'suite',
      navLabel: 'Designer',
      name: 'Designer Suite',
      tagline: 'Design workspace',
      description:
        'Schema design and API path modeling in one suite — canvas, versions, tags, and OpenAPI operations.',
      href: suiteHref,
      editorHref,
      icon: 'Layers',
      accent: 'from-violet-500 to-fuchsia-600',
      glow: 'group-hover:shadow-fuchsia-500/20',
      anyFeatureFlags: ['designer', 'paths'],
      external: isAbsoluteHref(suiteHref),
      enabled: true,
      showInNav: true,
      showOnHome: true,
      menuGroups: SUITE_MENU_GROUPS,
      menuItems: [
        {
          id: 'suite-home',
          label: 'Suite Home',
          description: 'Projects, activity and resume cards',
          href: suiteHref,
          icon: 'LayoutDashboard',
          group: 'design',
          external: isAbsoluteHref(suiteHref),
        },
        {
          id: 'suite-designer',
          label: 'Designer',
          description: 'Model schemas and reusable types',
          href: editorHref,
          icon: 'Palette',
          group: 'design',
          featureFlag: 'designer',
          accessNote: 'Included with the Designer plan. Ask a tenant admin to enable it.',
          external: isAbsoluteHref(editorHref),
        },
        {
          id: 'suite-paths',
          label: 'Paths Editor',
          description: 'Design operations and contracts',
          href: pathsHref,
          icon: 'Route',
          group: 'design',
          featureFlag: 'paths',
          accessNote: 'Included with the Paths plan. Ask a tenant admin to enable it.',
          external: isAbsoluteHref(pathsHref),
        },
        {
          id: 'authoring-overview',
          label: 'Authoring Overview',
          description: 'Coverage, releases, delivery and next actions',
          href: authoringHref(UI_AUTHORING_ROUTES.root),
          icon: 'Compass',
          group: 'authoring',
          // Enabled by UXE-1.2: the /ade/authoring route group now renders the
          // shared Authoring shell, so this destination resolves.
          external: isStudioSurface(),
        },
        {
          id: 'authoring-scribe',
          label: 'Scribe',
          description: 'AI-assisted content and guide workspace',
          href: authoringHref(UI_AUTHORING_ROUTES.scribe),
          icon: 'PenTool',
          group: 'authoring',
          badge: 'Preview',
          featureFlag: 'scribe',
          accessNote: 'Available in the Scribe preview. Contact your account team to join.',
          external: isStudioSurface(),
        },
        {
          id: 'authoring-slate',
          label: 'Slate',
          description: 'Portal design, preview and publishing',
          href: authoringHref(UI_AUTHORING_ROUTES.slate),
          icon: 'Layers',
          group: 'authoring',
          badge: 'Preview',
          featureFlag: 'slate',
          accessNote: 'Available in the Slate preview. Contact your account team to join.',
          external: isStudioSurface(),
        },
        {
          id: 'authoring-releases',
          label: 'Releases',
          description: 'Previews, production, promotion and rollback',
          href: authoringHref(UI_AUTHORING_ROUTES.releases),
          icon: 'Rocket',
          group: 'authoring',
          badge: 'Preview',
          featureFlag: 'hosted',
          accessNote: 'Included with a hosted plan. Contact your account team to upgrade.',
          external: isStudioSurface(),
        },
        {
          id: 'authoring-insights',
          label: 'Insights',
          description: 'Content, search, API, delivery and cost signals',
          href: authoringHref(UI_AUTHORING_ROUTES.insights),
          icon: 'BarChart3',
          group: 'authoring',
          badge: 'Preview',
          featureFlag: 'hosted',
          accessNote: 'Included with a hosted plan. Contact your account team to upgrade.',
          external: isStudioSurface(),
        },
      ],
    },
    {
      id: 'developer-suite',
      navLabel: 'Developer',
      name: 'Developer Suite',
      tagline: 'Developer tools',
      description:
        'SDKs, tooling, and developer workflows for your API specifications — coming soon.',
      href: '#',
      icon: 'Workflow',
      accent: 'from-sky-500 to-indigo-600',
      glow: 'group-hover:shadow-sky-500/20',
      enabled: false,
      external: false,
      showInNav: true,
      showOnHome: true,
      // Rendered as a disabled dropdown in nav until developer products ship.
      menuItems: [],
    },
  ];
}

export function isCommercialProductFlag(flagName: string): flagName is CommercialProductFlagName {
  return (COMMERCIAL_PRODUCT_FLAG_NAMES as readonly string[]).includes(flagName);
}
