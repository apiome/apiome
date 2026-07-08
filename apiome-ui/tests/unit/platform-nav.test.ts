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
    process.env.NEXT_PUBLIC_STUDIO_URL = originalStudioUrl;
  });

  it('exposes designer and paths through UI redirect routes on the main app', () => {
    delete process.env.NEXT_PUBLIC_APP_SURFACE;
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const items = getPlatformNavItems();
    expect(items.map((item) => item.id)).toEqual(['home', 'control-panel', 'designer', 'paths']);
    expect(resolvePlatformNavHref(items[2]!)).toBe('/ade/studio/editor');
    expect(platformNavItemIsActive(items[2]!, '/ade/studio/editor')).toBe(true);
  });

  it('uses direct studio routes and marks the active tab on the studio surface', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';

    const items = getPlatformNavItems();
    expect(resolvePlatformNavHref(items[2]!)).toBe('/editor');
    expect(platformNavItemIsActive(items[2]!, '/editor')).toBe(true);
    expect(isStudioSurface()).toBe(true);
  });
});
