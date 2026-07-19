import {
  COMMERCIAL_PRODUCT_FLAG_NAMES,
  SUITE_MENU_GROUPS,
  getBuiltinCommercialProducts,
} from '../../lib/commercial-products';

describe('commercial-products', () => {
  const originalSurface = process.env.NEXT_PUBLIC_APP_SURFACE;
  const originalStudioUrl = process.env.NEXT_PUBLIC_STUDIO_URL;
  const originalMainUrl = process.env.NEXT_PUBLIC_MAIN_APP_URL;

  afterEach(() => {
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

  it('ships designer suite and developer suite placeholders', () => {
    const products = getBuiltinCommercialProducts();
    expect(products.map((product) => product.id)).toEqual(['suite', 'developer-suite']);
    expect(products[0]?.anyFeatureFlags).toEqual(['designer', 'paths']);
    expect(products[0]?.navLabel).toBe('Designer');
    expect(products[0]?.name).toBe('Designer Suite');
    expect(products[0]?.menuItems?.map((item) => item.id)).toEqual([
      'suite-home',
      'suite-designer',
      'suite-paths',
      'authoring-overview',
      'authoring-scribe',
      'authoring-slate',
      'authoring-releases',
      'authoring-insights',
    ]);
    expect(products[1]?.enabled).toBe(false);
    expect(products[1]?.name).toBe('Developer Suite');
    expect(products[1]?.showInNav).toBe(true);
    expect(products[1]?.menuItems).toEqual([]);
    expect(COMMERCIAL_PRODUCT_FLAG_NAMES).toEqual([
      'designer',
      'paths',
      'scribe',
      'slate',
      'hosted',
    ]);
  });

  it('declares Design and Authoring groups and assigns every destination to one', () => {
    const suite = getBuiltinCommercialProducts()[0];

    expect(suite?.menuGroups).toEqual([
      { id: 'design', label: 'Design' },
      { id: 'authoring', label: 'Authoring' },
    ]);
    expect(SUITE_MENU_GROUPS).toBe(suite?.menuGroups);

    const groupIds = new Set(suite?.menuGroups?.map((group) => group.id));
    for (const menuItem of suite?.menuItems ?? []) {
      expect(groupIds.has(menuItem.group ?? '')).toBe(true);
    }
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

  it('enables authoring destinations and gates them by license flag', () => {
    const authoring = getBuiltinCommercialProducts()[0]?.menuItems?.filter(
      (item) => item.group === 'authoring'
    );

    for (const menuItem of authoring ?? []) {
      // UXE-1.1 shipped the contract with every destination held back; UXE-1.2
      // delivers the studio-served /authoring route group, so each resolves.
      expect(menuItem.enabled).not.toBe(false);
      expect(menuItem.href).toContain('/authoring');
      // Only a gated destination needs to explain how access is obtained;
      // Overview is ungated and shipped, so it has nothing to explain.
      if (menuItem.featureFlag) expect(menuItem.accessNote).toBeTruthy();
    }
    expect(authoring?.find((item) => item.id === 'authoring-scribe')?.featureFlag).toBe('scribe');
    expect(authoring?.find((item) => item.id === 'authoring-slate')?.featureFlag).toBe('slate');
    expect(authoring?.find((item) => item.id === 'authoring-releases')?.featureFlag).toBe('hosted');
    expect(authoring?.find((item) => item.id === 'authoring-insights')?.featureFlag).toBe('hosted');
    // Overview is Commercial MVP — available to any suite tenant, no extra flag.
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
    // Authoring is served by the studio app, so from here it links out exactly
    // like the Design destinations do.
    expect(
      products[0]?.menuItems?.filter((item) => item.group === 'authoring').map((item) => item.href)
    ).toEqual([
      'http://localhost:3003/authoring',
      'http://localhost:3003/authoring/scribe',
      'http://localhost:3003/authoring/slate',
      'http://localhost:3003/authoring/releases',
      'http://localhost:3003/authoring/insights',
    ]);
    expect(
      products[0]?.menuItems?.every((item) => item.group !== 'authoring' || item.external === true)
    ).toBe(true);
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

  it('keeps authoring in-app on the studio surface, which serves it', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const authoring = getBuiltinCommercialProducts()[0]?.menuItems?.filter(
      (item) => item.group === 'authoring'
    );
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
