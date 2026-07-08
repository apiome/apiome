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

  it('includes designer and paths from built-in commercial catalog', () => {
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://studio.example.com';

    const cards = getExternalHomeCards();
    expect(cards.map((card) => card.id)).toEqual(['designer', 'paths']);
    expect(cards[0]).toEqual(
      expect.objectContaining({
        id: 'designer',
        name: 'Data Designer',
        featureFlag: 'designer',
        href: 'https://studio.example.com/editor',
        external: true,
      })
    );
  });

  it('filters home cards and nav by license entitlements', () => {
    const entitled = new Set(['designer']);
    expect(getCommercialHomeCards(entitled).map((card) => card.id)).toEqual(['designer']);
    expect(getCommercialNavItems(entitled).map((item) => item.id)).toEqual(['designer']);
  });

  it('hides designer helpers when entitlement is missing', () => {
    expect(getDesignerHomeHref(new Set())).toBeNull();
    expect(buildDesignerEditorHref('p', 'v', new Set())).toBeNull();
  });

  it('builds designer deep links from NEXT_PUBLIC_STUDIO_URL when entitled', () => {
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://studio.example.com';
    const flags = new Set(['designer']);

    expect(getDesignerHomeHref(flags)).toBe('https://studio.example.com/editor');
    expect(getExternalNavItems()).toEqual([
      expect.objectContaining({ id: 'designer', label: 'Designer', href: 'https://studio.example.com/editor' }),
      expect.objectContaining({ id: 'paths', href: 'https://studio.example.com/paths' }),
    ]);
    expect(buildDesignerEditorHref('proj-1', 'ver-2', flags)).toBe(
      'https://studio.example.com/editor?projectId=proj-1&versionId=ver-2'
    );
  });

  it('resolves known lucide icon names', () => {
    expect(resolveExternalLinkIcon('Palette')).toBe(Palette);
  });
});
