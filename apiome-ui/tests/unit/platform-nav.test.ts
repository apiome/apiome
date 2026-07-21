import {
  getPlatformNavItems,
  isStudioSurface,
  platformNavItemIsActive,
  resolvePlatformNavHref,
} from '../../lib/platform-nav';
import {
  clearAuthoringSuiteFixture,
  registerAuthoringSuiteFixture,
} from '../helpers/authoring-suite-fixture';

describe('platform-nav', () => {
  const originalSurface = process.env.NEXT_PUBLIC_APP_SURFACE;
  const originalStudioUrl = process.env.NEXT_PUBLIC_STUDIO_URL;

  afterEach(() => {
    clearAuthoringSuiteFixture();
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

  describe('Designer trigger active routes', () => {
    const suite = { id: 'suite', label: 'Designer', href: '/ade/studio' };

    it('stays active across design routes; contributed paths extend the trigger', () => {
      process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
      registerAuthoringSuiteFixture();

      expect(platformNavItemIsActive(suite, '/editor')).toBe(true);
      expect(platformNavItemIsActive(suite, '/authoring')).toBe(true);
      expect(platformNavItemIsActive(suite, '/authoring/scribe')).toBe(true);
    });

    it('does not treat lookalike routes as contributed destinations', () => {
      process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
      registerAuthoringSuiteFixture();

      expect(platformNavItemIsActive(suite, '/authoring-archive')).toBe(false);
      expect(platformNavItemIsActive(suite, null)).toBe(false);

      delete process.env.NEXT_PUBLIC_APP_SURFACE;
      expect(platformNavItemIsActive(suite, '/ade/dashboard')).toBe(false);
    });

    it('never matches contributed studio-only routes on the main surface', () => {
      delete process.env.NEXT_PUBLIC_APP_SURFACE;
      registerAuthoringSuiteFixture();

      expect(platformNavItemIsActive(suite, '/ade/studio')).toBe(true);
      expect(platformNavItemIsActive(suite, '/authoring')).toBe(false);
    });

    it('without a contribution, only built-in studio routes activate the trigger', () => {
      process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';

      expect(platformNavItemIsActive(suite, '/editor')).toBe(true);
      expect(platformNavItemIsActive(suite, '/authoring')).toBe(false);
    });
  });
});
