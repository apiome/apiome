import { Palette } from 'lucide-react';
import {
  buildDesignerEditorHref,
  getCommercialHomeCards,
  getCommercialNavItems,
  getDesignerHomeHref,
  getExternalHomeCards,
  getExternalNavItems,
  groupNavMenuItems,
  isNavMenuItemNavigable,
  resolveExternalLinkIcon,
} from '../../lib/external-links';

describe('external-links (commercial products)', () => {
  const originalStudioUrl = process.env.NEXT_PUBLIC_STUDIO_URL;
  const originalSurface = process.env.NEXT_PUBLIC_APP_SURFACE;

  afterEach(() => {
    if (originalStudioUrl === undefined) {
      delete process.env.NEXT_PUBLIC_STUDIO_URL;
    } else {
      process.env.NEXT_PUBLIC_STUDIO_URL = originalStudioUrl;
    }
    process.env.NEXT_PUBLIC_APP_SURFACE = originalSurface;
  });

  it('includes designer suite and coming-soon developer suite from built-in catalog', () => {
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://studio.example.com';

    const cards = getExternalHomeCards();
    expect(cards.map((card) => card.id)).toEqual(['suite', 'developer-suite']);
    expect(cards[0]).toEqual(
      expect.objectContaining({
        id: 'suite',
        name: 'Designer Suite',
        anyFeatureFlags: ['designer', 'paths'],
        href: 'https://studio.example.com/',
        external: true,
        enabled: true,
      })
    );
    expect(cards[1]).toEqual(
      expect.objectContaining({
        id: 'developer-suite',
        name: 'Developer Suite',
        enabled: false,
      })
    );
  });

  it('filters home cards and nav by license entitlements', () => {
    const entitled = new Set(['designer']);
    expect(getCommercialHomeCards(entitled).map((card) => card.id)).toEqual([
      'suite',
      'developer-suite',
    ]);
    // Disabled developer suite stays in nav (rendered shaded as coming soon).
    expect(getCommercialNavItems(entitled).map((item) => item.id)).toEqual([
      'suite',
      'developer-suite',
    ]);
    // Suite dropdown destinations are kept but annotated, so the menu can
    // explain access (UXE-1.1) instead of silently hiding products.
    const suiteMenu = getCommercialNavItems(entitled)[0]?.menuItems ?? [];
    expect(suiteMenu.filter((item) => item.entitled).map((item) => item.id)).toEqual([
      'suite-home',
      'suite-designer',
      'authoring-overview',
    ]);
    // No paths flag → the destination stays visible but carries no resource URL.
    const paths = suiteMenu.find((item) => item.id === 'suite-paths');
    expect(paths?.entitled).toBe(false);
    expect(paths?.href).toBe('');
    expect(paths?.accessNote).toBeTruthy();

    const pathsOnly = new Set(['paths']);
    expect(getCommercialHomeCards(pathsOnly).map((card) => card.id)).toEqual([
      'suite',
      'developer-suite',
    ]);
    expect(
      getCommercialNavItems(pathsOnly)[0]
        ?.menuItems?.filter((item) => item.entitled)
        .map((item) => item.id)
    ).toEqual(['suite-home', 'suite-paths', 'authoring-overview']);

    expect(getCommercialHomeCards(new Set()).map((card) => card.id)).toEqual(['developer-suite']);
    expect(getCommercialNavItems(new Set()).map((item) => item.id)).toEqual(['developer-suite']);
  });

  it('hides designer helpers when entitlement is missing', () => {
    expect(getDesignerHomeHref(new Set())).toBeNull();
    expect(buildDesignerEditorHref('p', 'v', new Set())).toBeNull();
  });

  it('builds designer deep links from NEXT_PUBLIC_STUDIO_URL when entitled', () => {
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://studio.example.com';
    const flags = new Set(['designer']);

    expect(getDesignerHomeHref(flags)).toBe('https://studio.example.com/');
    expect(getExternalNavItems()).toEqual([
      expect.objectContaining({
        id: 'suite',
        label: 'Designer',
        href: 'https://studio.example.com/',
      }),
      expect.objectContaining({ id: 'developer-suite', label: 'Developer', enabled: false }),
    ]);
    expect(buildDesignerEditorHref('proj-1', 'ver-2', flags)).toBe(
      'https://studio.example.com/editor?projectId=proj-1&versionId=ver-2'
    );
  });

  it('resolves known lucide icon names', () => {
    expect(resolveExternalLinkIcon('Palette')).toBe(Palette);
  });

  describe('groupNavMenuItems (UXE-1.1)', () => {
    it('splits suite destinations into declared group order', () => {
      const suite = getCommercialNavItems(new Set(['designer', 'paths']))[0]!;
      const groups = groupNavMenuItems(suite);

      expect(groups.map((group) => group.label)).toEqual(['Design', 'Authoring']);
      expect(groups[0].items.map((item) => item.id)).toEqual([
        'suite-home',
        'suite-designer',
        'suite-paths',
      ]);
      expect(groups[1].items.map((item) => item.id)).toEqual([
        'authoring-overview',
        'authoring-scribe',
        'authoring-slate',
        'authoring-releases',
        'authoring-insights',
      ]);
    });

    it('makes every authoring destination navigable now the route group ships (UXE-1.2)', () => {
      const suite = getCommercialNavItems(
        new Set(['designer', 'paths', 'scribe', 'slate', 'hosted'])
      )[0]!;
      const authoring = groupNavMenuItems(suite)[1].items;

      // Every destination now resolves to a real page under the studio-served
      // /authoring group, so none is held back with `enabled: false`.
      for (const item of authoring) {
        expect(item.enabled).not.toBe(false);
        expect(isNavMenuItemNavigable(item)).toBe(true);
        expect(item.href).toContain('/authoring');
      }
    });

    it('keeps ungrouped destinations in one unlabeled leading group', () => {
      const groups = groupNavMenuItems({
        id: 'legacy',
        label: 'Legacy',
        href: '/legacy',
        menuItems: [
          { id: 'a', label: 'A', href: '/a' },
          // An unknown group id falls back rather than creating a stray heading.
          { id: 'b', label: 'B', href: '/b', group: 'nope' },
        ],
      });

      expect(groups).toHaveLength(1);
      expect(groups[0].label).toBe('');
      expect(groups[0].items.map((item) => item.id)).toEqual(['a', 'b']);
    });

    it('drops groups that have no destinations and handles empty menus', () => {
      expect(
        groupNavMenuItems({
          id: 'empty',
          label: 'Empty',
          href: '#',
          menuItems: [],
          menuGroups: [{ id: 'design', label: 'Design' }],
        })
      ).toEqual([]);
      expect(groupNavMenuItems({ id: 'none', label: 'None', href: '#' })).toEqual([]);
    });
  });

  describe('isNavMenuItemNavigable', () => {
    it('requires a shipped, entitled destination with an href', () => {
      expect(isNavMenuItemNavigable({ id: 'a', label: 'A', href: '/a' })).toBe(true);
      expect(isNavMenuItemNavigable({ id: 'a', label: 'A', href: '/a', enabled: false })).toBe(
        false
      );
      expect(isNavMenuItemNavigable({ id: 'a', label: 'A', href: '', entitled: false })).toBe(
        false
      );
    });
  });
});
