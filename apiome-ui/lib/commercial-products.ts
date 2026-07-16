import { getStudioAppUrl } from './app-urls';
import type { ExternalLinkEntry } from './external-links';
import { STUDIO_APP_ROUTES } from './studio-routes';

/** Feature-flag slugs that map to first-party commercial applications on the home grid. */
export const COMMERCIAL_PRODUCT_FLAG_NAMES = ['designer', 'paths'] as const;

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
      menuItems: [
        {
          id: 'suite-home',
          label: 'Home',
          description: 'Suite home dashboard',
          href: suiteHref,
          icon: 'LayoutDashboard',
          external: isAbsoluteHref(suiteHref),
        },
        {
          id: 'suite-designer',
          label: 'Designer',
          description: 'Model schemas on the canvas',
          href: editorHref,
          icon: 'Palette',
          featureFlag: 'designer',
          external: isAbsoluteHref(editorHref),
        },
        {
          id: 'suite-paths',
          label: 'Paths Editor',
          description: 'Author OpenAPI paths and operations',
          href: pathsHref,
          icon: 'Route',
          featureFlag: 'paths',
          external: isAbsoluteHref(pathsHref),
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
