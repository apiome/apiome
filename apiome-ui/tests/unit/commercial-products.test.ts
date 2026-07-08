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

  it('ships designer and paths with feature-flag slugs', () => {
    const products = getBuiltinCommercialProducts();
    expect(products.map((product) => product.id)).toEqual(['designer', 'paths']);
    expect(products[0]?.featureFlag).toBe('designer');
    expect(products[1]?.featureFlag).toBe('paths');
    expect(COMMERCIAL_PRODUCT_FLAG_NAMES).toEqual(['designer', 'paths']);
  });

  it('points to the studio site when not on the studio surface', () => {
    delete process.env.NEXT_PUBLIC_APP_SURFACE;
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const products = getBuiltinCommercialProducts();
    expect(products[0]?.href).toBe('http://localhost:3003/editor');
    expect(products[1]?.href).toBe('http://localhost:3003/paths');
    expect(products[0]?.external).toBe(true);
    expect(products[1]?.external).toBe(true);
  });

  it('uses in-app studio routes on the studio surface', () => {
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'http://localhost:3003';

    const products = getBuiltinCommercialProducts();
    expect(products[0]?.href).toBe('/editor');
    expect(products[1]?.href).toBe('/paths');
    expect(products[0]?.external).toBe(false);
  });
});
