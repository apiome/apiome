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

function resolveStudioEditorHref(): string {
  return resolveStudioSurfaceHref(STUDIO_APP_ROUTES.editor);
}

function resolveStudioPathsHref(): string {
  return resolveStudioSurfaceHref(STUDIO_APP_ROUTES.paths);
}

function isAbsoluteHref(href: string): boolean {
  return href.startsWith('http://') || href.startsWith('https://');
}

/**
 * Built-in commercial applications shipped with apiome-ui.
 * Visibility is gated by license feature flags (`designer`, `paths`) in admin.
 */
export function getBuiltinCommercialProducts(): ExternalLinkEntry[] {
  const designerHref = resolveStudioEditorHref();
  const pathsHref = resolveStudioPathsHref();

  return [
    {
      id: 'designer',
      navLabel: 'Designer',
      name: 'Data Designer',
      tagline: 'Schema design',
      description:
        'Model classes on an interactive canvas with versions, tags, and live validation.',
      href: designerHref,
      editorHref: designerHref,
      icon: 'Palette',
      accent: 'from-violet-500 to-fuchsia-600',
      glow: 'group-hover:shadow-fuchsia-500/20',
      featureFlag: 'designer',
      external: isAbsoluteHref(designerHref),
      enabled: true,
      showInNav: true,
      showOnHome: true,
    },
    {
      id: 'paths',
      navLabel: 'Paths',
      name: 'API Paths',
      tagline: 'OpenAPI operations',
      description:
        'Design paths, operations, request bodies, and responses for your API surface.',
      href: pathsHref,
      icon: 'Route',
      accent: 'from-emerald-500 to-teal-600',
      glow: 'group-hover:shadow-emerald-500/20',
      featureFlag: 'paths',
      external: isAbsoluteHref(pathsHref),
      enabled: true,
      showInNav: true,
      showOnHome: true,
    },
  ];
}

export function isCommercialProductFlag(flagName: string): flagName is CommercialProductFlagName {
  return (COMMERCIAL_PRODUCT_FLAG_NAMES as readonly string[]).includes(flagName);
}
