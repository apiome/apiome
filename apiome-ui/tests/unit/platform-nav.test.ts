import {
  getPlatformNavItems,
  isStudioSurface,
  platformNavItemIsActive,
  resolvePlatformNavHref,
} from '../../lib/platform-nav';

describe('platform-nav', () => {
  const originalSurface = process.env.NEXT_PUBLIC_APP_SURFACE;
  const originalStudioUrl = process.env.NEXT_PUBLIC_STUDIO_URL;

  afterEach(() => {
    process.env.NEXT_PUBLIC_APP_SURFACE = originalSurface;
    if (originalStudioUrl === undefined) {
      delete process.env.NEXT_PUBLIC_STUDIO_URL;
    } else {
      process.env.NEXT_PUBLIC_STUDIO_URL = originalStudioUrl;
    }
  });

  it('uses configured commercial hrefs from external links', () => {
    delete process.env.NEXT_PUBLIC_APP_SURFACE;
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const items = getPlatformNavItems();
    expect(items.map((item) => item.id)).toEqual(['home', 'control-panel']);

    const designer = {
      id: 'designer',
      label: 'Designer',
      href: 'http://localhost:3003/editor',
      external: true,
    };
    expect(resolvePlatformNavHref(designer)).toBe('http://localhost:3003/editor');
    expect(
      platformNavItemIsActive({ id: 'designer', label: 'Designer', href: '/ade/studio/editor' }, '/ade/studio/editor')
    ).toBe(true);
  });

  it('uses direct studio routes when commercial items are passed in', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
    process.env.NEXT_PUBLIC_MAIN_APP_URL = 'http://localhost:3000';

    const commercial = [
      { id: 'designer', label: 'Designer', href: '/editor' },
      { id: 'paths', label: 'Paths', href: '/paths' },
    ];
    const items = getPlatformNavItems(commercial);
    expect(items[0]?.href).toBe('http://localhost:3000/ade');
    expect(items[2]?.href).toBe('/editor');
    expect(resolvePlatformNavHref(items[2]!)).toBe('/editor');
    expect(platformNavItemIsActive(items[2]!, '/editor')).toBe(true);
    expect(isStudioSurface()).toBe(true);
  });
});
