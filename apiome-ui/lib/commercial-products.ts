import { getStudioAppUrl } from './app-urls';
import type { ExternalLinkEntry, ExternalNavMenuGroup } from './external-links';
import { STUDIO_APP_ROUTES } from './studio-routes';
import { tryLoadOptionalSuiteHost } from './suite-contract';

/**
 * Feature-flag slugs that map to first-party commercial applications.
 * Product-specific destinations may contribute additional opaque flag names
 * via the suite contract; these builtins gate the Design group and remain
 * available for license entitlement lookups.
 */
export const COMMERCIAL_PRODUCT_FLAG_NAMES = [
  'designer',
  'paths',
  'scribe',
  'slate',
  'hosted',
] as const;

/** Ordered group headings for the built-in Designer suite dropdown (Design only). */
export const SUITE_MENU_GROUPS: ExternalNavMenuGroup[] = [{ id: 'design', label: 'Design' }];

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
 *
 * Additional suite destinations are contributed at runtime via
 * {@link contributeSuiteMenu} from a commercial host package.
 */
export function getBuiltinCommercialProducts(): ExternalLinkEntry[] {
  tryLoadOptionalSuiteHost();

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
