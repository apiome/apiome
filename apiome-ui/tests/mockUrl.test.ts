import { buildMockBaseUrl, getMockPublicBaseUrl } from '../lib/mock/mockUrl';

describe('getMockPublicBaseUrl', () => {
  const original = process.env.APIOME_MOCK_PUBLIC_BASE_URL;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.APIOME_MOCK_PUBLIC_BASE_URL;
    } else {
      process.env.APIOME_MOCK_PUBLIC_BASE_URL = original;
    }
  });

  it('defaults to localhost:8775 when unset', () => {
    delete process.env.APIOME_MOCK_PUBLIC_BASE_URL;
    expect(getMockPublicBaseUrl()).toBe('http://localhost:8775');
  });

  it('reads APIOME_MOCK_PUBLIC_BASE_URL and strips trailing slashes', () => {
    process.env.APIOME_MOCK_PUBLIC_BASE_URL = 'https://mock.example.com///';
    expect(getMockPublicBaseUrl()).toBe('https://mock.example.com');
  });
});

describe('buildMockBaseUrl', () => {
  it('composes tenant/project/version under the mock host', () => {
    expect(buildMockBaseUrl('http://localhost:8775', 'acme', 'petstore', '1.0.0')).toBe(
      'http://localhost:8775/acme/petstore/1.0.0'
    );
  });

  it('returns null when any segment is missing', () => {
    expect(buildMockBaseUrl('http://localhost:8775', '', 'petstore', '1.0.0')).toBeNull();
    expect(buildMockBaseUrl('http://localhost:8775', 'acme', '', '1.0.0')).toBeNull();
    expect(buildMockBaseUrl('http://localhost:8775', 'acme', 'petstore', '')).toBeNull();
  });
});
