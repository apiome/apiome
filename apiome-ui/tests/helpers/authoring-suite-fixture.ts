/**
 * Test fixture: commercial suite menu contribution (mirrors private-suite host).
 *
 * Open-source builtins ship Design only; Authoring destinations arrive via the
 * suite contract. Tests that exercise the full Designer dropdown register this
 * contribution in beforeEach.
 */
import {
  contributeSuiteMenu,
  resetSuiteMenuContribution,
  type SuiteMenuContribution,
} from '../../lib/suite-contract';

function isAbsoluteHref(href: string): boolean {
  return href.startsWith('http://') || href.startsWith('https://');
}

function resolveStudioSurfaceHref(path: string): string {
  if (process.env.NEXT_PUBLIC_APP_SURFACE === 'studio') return path;
  const base = process.env.NEXT_PUBLIC_STUDIO_URL?.replace(/\/+$/, '') || 'http://localhost:3003';
  return `${base}${path}`;
}

/** Build the Authoring group contribution with surface-aware hrefs. */
export function buildAuthoringSuiteContribution(): SuiteMenuContribution {
  const overview = resolveStudioSurfaceHref('/authoring');
  const scribe = resolveStudioSurfaceHref('/authoring/scribe');
  const slate = resolveStudioSurfaceHref('/authoring/slate');
  const releases = resolveStudioSurfaceHref('/authoring/releases');
  const insights = resolveStudioSurfaceHref('/authoring/insights');

  return {
    menuGroups: [{ id: 'authoring', label: 'Authoring' }],
    featureFlagNames: ['scribe', 'slate', 'hosted'],
    menuItems: [
      {
        id: 'authoring-overview',
        label: 'Authoring Overview',
        description: 'Coverage, releases, delivery and next actions',
        href: overview,
        icon: 'Compass',
        group: 'authoring',
        external: isAbsoluteHref(overview),
      },
      {
        id: 'authoring-scribe',
        label: 'Scribe',
        description: 'AI-assisted content and guide workspace',
        href: scribe,
        icon: 'PenTool',
        group: 'authoring',
        badge: 'Preview',
        featureFlag: 'scribe',
        accessNote: 'Available in the Scribe preview. Contact your account team to join.',
        external: isAbsoluteHref(scribe),
      },
      {
        id: 'authoring-slate',
        label: 'Slate',
        description: 'Portal design, preview and publishing',
        href: slate,
        icon: 'Layers',
        group: 'authoring',
        badge: 'Preview',
        featureFlag: 'slate',
        accessNote: 'Available in the Slate preview. Contact your account team to join.',
        external: isAbsoluteHref(slate),
      },
      {
        id: 'authoring-releases',
        label: 'Releases',
        description: 'Previews, production, promotion and rollback',
        href: releases,
        icon: 'Rocket',
        group: 'authoring',
        badge: 'Preview',
        featureFlag: 'hosted',
        accessNote: 'Included with a hosted plan. Contact your account team to upgrade.',
        external: isAbsoluteHref(releases),
      },
      {
        id: 'authoring-insights',
        label: 'Insights',
        description: 'Content, search, API, delivery and cost signals',
        href: insights,
        icon: 'BarChart3',
        group: 'authoring',
        badge: 'Preview',
        featureFlag: 'hosted',
        accessNote: 'Included with a hosted plan. Contact your account team to upgrade.',
        external: isAbsoluteHref(insights),
      },
    ],
    isActive: (pathname: string) => {
      if (process.env.NEXT_PUBLIC_APP_SURFACE !== 'studio') return false;
      return pathname === '/authoring' || pathname.startsWith('/authoring/');
    },
  };
}

/** Register the fixture contribution (call in beforeEach). */
export function registerAuthoringSuiteFixture(): void {
  contributeSuiteMenu(buildAuthoringSuiteContribution());
}

/** Clear the contribution (call in afterEach). */
export function clearAuthoringSuiteFixture(): void {
  resetSuiteMenuContribution();
}
