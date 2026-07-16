import { Palette } from 'lucide-react';
import {
  buildDesignerEditorHref,
  getCommercialHomeCards,
  getCommercialNavItems,
  getDesignerHomeHref,
  getExternalHomeCards,
  getExternalNavItems,
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
    expect(getCommercialNavItems(entitled).map((item) => item.id)).toEqual(['suite']);

    const pathsOnly = new Set(['paths']);
    expect(getCommercialHomeCards(pathsOnly).map((card) => card.id)).toEqual([
      'suite',
      'developer-suite',
    ]);

    expect(getCommercialHomeCards(new Set()).map((card) => card.id)).toEqual(['developer-suite']);
    expect(getCommercialNavItems(new Set()).map((item) => item.id)).toEqual([]);
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
      expect.objectContaining({ id: 'suite', label: 'Suite', href: 'https://studio.example.com/' }),
    ]);
    expect(buildDesignerEditorHref('proj-1', 'ver-2', flags)).toBe(
      'https://studio.example.com/editor?projectId=proj-1&versionId=ver-2'
    );
  });

  it('resolves known lucide icon names', () => {
    expect(resolveExternalLinkIcon('Palette')).toBe(Palette);
  });
});
