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

    const suite = {
      id: 'suite',
      label: 'Suite',
      href: 'http://localhost:3003/',
      external: true,
    };
    expect(resolvePlatformNavHref(suite)).toBe('http://localhost:3003/');
    expect(
      platformNavItemIsActive({ id: 'suite', label: 'Suite', href: '/ade/studio' }, '/ade/studio/editor')
    ).toBe(true);
  });

  it('uses direct studio routes when commercial items are passed in', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
    process.env.NEXT_PUBLIC_MAIN_APP_URL = 'http://localhost:3000';

    const commercial = [{ id: 'suite', label: 'Suite', href: '/' }];
    const items = getPlatformNavItems(commercial);
    expect(items[0]?.href).toBe('http://localhost:3000/ade');
    expect(items[2]?.href).toBe('/');
    expect(resolvePlatformNavHref(items[2]!)).toBe('/');
    expect(platformNavItemIsActive(items[2]!, '/')).toBe(true);
    expect(platformNavItemIsActive(items[2]!, '/editor')).toBe(true);
    expect(platformNavItemIsActive(items[2]!, '/paths')).toBe(true);
    expect(isStudioSurface()).toBe(true);
  });
});
