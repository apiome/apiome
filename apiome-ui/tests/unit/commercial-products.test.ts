import {
  COMMERCIAL_PRODUCT_FLAG_NAMES,
  SUITE_MENU_GROUPS,
  getBuiltinCommercialProducts,
  getCommercialProductFlagNames,
  isCommercialProductFlag,
} from '../../lib/commercial-products';
import {
  clearAuthoringSuiteFixture,
  registerAuthoringSuiteFixture,
} from '../helpers/authoring-suite-fixture';
import { getCommercialNavItems } from '../../lib/external-links';

describe('commercial-products', () => {
  const originalSurface = process.env.NEXT_PUBLIC_APP_SURFACE;
  const originalStudioUrl = process.env.NEXT_PUBLIC_STUDIO_URL;
  const originalMainUrl = process.env.NEXT_PUBLIC_MAIN_APP_URL;

  afterEach(() => {
    clearAuthoringSuiteFixture();
    process.env.NEXT_PUBLIC_APP_SURFACE = originalSurface;
    if (originalStudioUrl === undefined) {
      delete process.env.NEXT_PUBLIC_STUDIO_URL;
    } else {
      process.env.NEXT_PUBLIC_STUDIO_URL = originalStudioUrl;
    }
    if (originalMainUrl === undefined) {
      delete process.env.NEXT_PUBLIC_MAIN_APP_URL;
    } else {
      process.env.NEXT_PUBLIC_MAIN_APP_URL = originalMainUrl;
    }
  });

  it('ships designer suite and developer suite placeholders with Design destinations only', () => {
    const products = getBuiltinCommercialProducts();
    expect(products.map((product) => product.id)).toEqual(['suite', 'developer-suite']);
    expect(products[0]?.anyFeatureFlags).toEqual(['designer', 'paths']);
    expect(products[0]?.navLabel).toBe('Designer');
    expect(products[0]?.name).toBe('Designer Suite');
    expect(products[0]?.menuItems?.map((item) => item.id)).toEqual([
      'suite-home',
      'suite-designer',
      'suite-paths',
    ]);
    expect(products[0]?.menuGroups).toEqual([{ id: 'design', label: 'Design' }]);
    expect(SUITE_MENU_GROUPS).toBe(products[0]?.menuGroups);
    expect(products[1]?.enabled).toBe(false);
    expect(products[1]?.name).toBe('Developer Suite');
    expect(products[1]?.showInNav).toBe(true);
    expect(products[1]?.menuItems).toEqual([]);
    // The open-source builtins name only the Design group; commercial
    // (Authoring) slugs are never hardcoded here (#2466).
    expect(COMMERCIAL_PRODUCT_FLAG_NAMES).toEqual(['designer', 'paths']);
  });

  it('resolves only the Design builtins as product flags without a host', () => {
    expect(getCommercialProductFlagNames()).toEqual(['designer', 'paths']);
    expect(isCommercialProductFlag('designer')).toBe(true);
    expect(isCommercialProductFlag('paths')).toBe(true);
    // No commercial host linked: authoring slugs are not product flags here.
    expect(isCommercialProductFlag('scribe')).toBe(false);
    expect(isCommercialProductFlag('slate')).toBe(false);
    expect(isCommercialProductFlag('hosted')).toBe(false);
    expect(isCommercialProductFlag('unknown')).toBe(false);
  });

  it('merges contributed commercial slugs from the suite host at runtime', () => {
    registerAuthoringSuiteFixture();

    // Builtins first, then the host-contributed Authoring slugs, de-duplicated.
    expect(getCommercialProductFlagNames()).toEqual([
      'designer',
      'paths',
      'scribe',
      'slate',
      'hosted',
    ]);
    expect(isCommercialProductFlag('scribe')).toBe(true);
    expect(isCommercialProductFlag('slate')).toBe(true);
    expect(isCommercialProductFlag('hosted')).toBe(true);
    // The static builtin list is unchanged by a contribution.
    expect(COMMERCIAL_PRODUCT_FLAG_NAMES).toEqual(['designer', 'paths']);
  });

  it('merges a suite-contract contribution into the Designer dropdown', () => {
    registerAuthoringSuiteFixture();
    const suite = getCommercialNavItems(new Set(['designer', 'paths']))[0];

    expect(suite?.menuGroups).toEqual([
      { id: 'design', label: 'Design' },
      { id: 'authoring', label: 'Authoring' },
    ]);
    expect(
      suite?.menuItems?.filter((item) => item.group === 'authoring').map((item) => item.id)
    ).toEqual([
      'authoring-overview',
      'authoring-scribe',
      'authoring-slate',
      'authoring-releases',
      'authoring-insights',
    ]);
  });

  it('gates contributed destinations by license flag with access notes', () => {
    registerAuthoringSuiteFixture();
    const authoring = getCommercialNavItems(
      new Set(['designer', 'paths', 'scribe', 'slate', 'hosted'])
    )[0]?.menuItems?.filter((item) => item.group === 'authoring');

    for (const menuItem of authoring ?? []) {
      expect(menuItem.enabled).not.toBe(false);
      expect(menuItem.href).toContain('/authoring');
      if (menuItem.featureFlag) expect(menuItem.accessNote).toBeTruthy();
    }
    expect(authoring?.find((item) => item.id === 'authoring-scribe')?.featureFlag).toBe('scribe');
    expect(authoring?.find((item) => item.id === 'authoring-slate')?.featureFlag).toBe('slate');
    expect(authoring?.find((item) => item.id === 'authoring-releases')?.featureFlag).toBe('hosted');
    expect(authoring?.find((item) => item.id === 'authoring-insights')?.featureFlag).toBe('hosted');
    expect(authoring?.find((item) => item.id === 'authoring-overview')?.featureFlag).toBeUndefined();
  });

  it('points to the studio site root when not on the studio surface', () => {
    delete process.env.NEXT_PUBLIC_APP_SURFACE;
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const products = getBuiltinCommercialProducts();
    expect(products[0]?.href).toBe('http://localhost:3003/');
    expect(products[0]?.editorHref).toBe('http://localhost:3003/editor');
    expect(products[0]?.external).toBe(true);
    expect(
      products[0]?.menuItems?.filter((item) => item.group === 'design').map((item) => item.href)
    ).toEqual([
      'http://localhost:3003/',
      'http://localhost:3003/editor',
      'http://localhost:3003/paths',
    ]);
  });

  it('uses in-app studio root on the studio surface', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const products = getBuiltinCommercialProducts();
    expect(products[0]?.href).toBe('/');
    expect(products[0]?.editorHref).toBe('/editor');
    expect(products[0]?.external).toBe(false);
    expect(
      products[0]?.menuItems?.filter((item) => item.group === 'design').map((item) => item.href)
    ).toEqual(['/', '/editor', '/paths']);
  });

  it('resolves contributed destinations in-app on the studio surface', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';
    registerAuthoringSuiteFixture();

    const authoring = getCommercialNavItems(new Set(['designer', 'paths', 'scribe', 'slate', 'hosted']))[0]
      ?.menuItems?.filter((item) => item.group === 'authoring');
    expect(authoring?.map((item) => item.href)).toEqual([
      '/authoring',
      '/authoring/scribe',
      '/authoring/slate',
      '/authoring/releases',
      '/authoring/insights',
    ]);
    expect(authoring?.every((item) => item.external === false)).toBe(true);
  });
});
