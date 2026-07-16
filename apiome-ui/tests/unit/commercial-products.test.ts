import { COMMERCIAL_PRODUCT_FLAG_NAMES, getBuiltinCommercialProducts } from '../../lib/commercial-products';

describe('commercial-products', () => {
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

  it('ships designer suite and developer suite placeholders', () => {
    const products = getBuiltinCommercialProducts();
    expect(products.map((product) => product.id)).toEqual(['suite', 'developer-suite']);
    expect(products[0]?.anyFeatureFlags).toEqual(['designer', 'paths']);
    expect(products[0]?.navLabel).toBe('Suite');
    expect(products[0]?.name).toBe('Designer Suite');
    expect(products[1]?.enabled).toBe(false);
    expect(products[1]?.name).toBe('Developer Suite');
    expect(COMMERCIAL_PRODUCT_FLAG_NAMES).toEqual(['designer', 'paths']);
  });

  it('points to the studio site root when not on the studio surface', () => {
    delete process.env.NEXT_PUBLIC_APP_SURFACE;
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const products = getBuiltinCommercialProducts();
    expect(products[0]?.href).toBe('http://localhost:3003/');
    expect(products[0]?.editorHref).toBe('http://localhost:3003/editor');
    expect(products[0]?.external).toBe(true);
  });

  it('uses in-app studio root on the studio surface', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const products = getBuiltinCommercialProducts();
    expect(products[0]?.href).toBe('/');
    expect(products[0]?.editorHref).toBe('/editor');
    expect(products[0]?.external).toBe(false);
  });
});
