import {
  applyUiMockBaseUrl,
  buildGraphqlMockUrl,
  buildMockBaseUrl,
  isAsyncapiSourceFormat,
  isGraphqlSourceFormat,
  getMockPublicBaseUrl,
  rewriteMockUrlHost,
} from '../lib/mock/mockUrl';

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

describe('rewriteMockUrlHost', () => {
  const original = process.env.APIOME_MOCK_PUBLIC_BASE_URL;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.APIOME_MOCK_PUBLIC_BASE_URL;
    } else {
      process.env.APIOME_MOCK_PUBLIC_BASE_URL = original;
    }
  });

  it('replaces REST localhost origin with the UI-configured host', () => {
    process.env.APIOME_MOCK_PUBLIC_BASE_URL = 'https://mock.apiome.dev';
    expect(rewriteMockUrlHost('http://localhost:8775/acme/petstore/1.0.0')).toBe(
      'https://mock.apiome.dev/acme/petstore/1.0.0'
    );
  });

  it('returns null for empty input', () => {
    expect(rewriteMockUrlHost(null)).toBeNull();
    expect(rewriteMockUrlHost(undefined)).toBeNull();
  });
});

describe('applyUiMockBaseUrl', () => {
  const original = process.env.APIOME_MOCK_PUBLIC_BASE_URL;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.APIOME_MOCK_PUBLIC_BASE_URL;
    } else {
      process.env.APIOME_MOCK_PUBLIC_BASE_URL = original;
    }
  });

  it('rewrites mockBaseUrl from REST for enabled published mocks', () => {
    process.env.APIOME_MOCK_PUBLIC_BASE_URL = 'https://mock.apiome.dev';
    const result = applyUiMockBaseUrl(
      {
        mockEnabled: true,
        published: true,
        mockBaseUrl: 'http://localhost:8775/acme/petstore/1.0.0',
      },
      'acme'
    );
    expect(result.mockBaseUrl).toBe('https://mock.apiome.dev/acme/petstore/1.0.0');
  });

  it('clears mockBaseUrl when mock is disabled', () => {
    process.env.APIOME_MOCK_PUBLIC_BASE_URL = 'https://mock.apiome.dev';
    const result = applyUiMockBaseUrl(
      {
        mockEnabled: false,
        published: true,
        mockBaseUrl: 'http://localhost:8775/acme/petstore/1.0.0',
      },
      'acme'
    );
    expect(result.mockBaseUrl).toBeNull();
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

describe('GraphQL mock URLs (#5729)', () => {
  it('recognises GraphQL source formats, federated ones included', () => {
    expect(isGraphqlSourceFormat('graphql')).toBe(true);
    expect(isGraphqlSourceFormat(' GraphQL-Federation ')).toBe(true);
    expect(isGraphqlSourceFormat('openapi-3.1')).toBe(false);
    expect(isGraphqlSourceFormat(null)).toBe(false);
    expect(isGraphqlSourceFormat(undefined)).toBe(false);
  });

  it('appends /graphql to the mock base URL', () => {
    expect(buildGraphqlMockUrl('https://mock.example/a/b/1.0.0')).toBe('https://mock.example/a/b/1.0.0/graphql');
    expect(buildGraphqlMockUrl('https://mock.example/a/b/1.0.0/')).toBe('https://mock.example/a/b/1.0.0/graphql');
    expect(buildGraphqlMockUrl(null)).toBeNull();
  });
});

describe('AsyncAPI source formats (#5735)', () => {
  it('recognises every asyncapi version and nothing else', () => {
    expect(isAsyncapiSourceFormat('asyncapi-3')).toBe(true);
    expect(isAsyncapiSourceFormat(' AsyncAPI-2.6 ')).toBe(true);
    expect(isAsyncapiSourceFormat('openapi-3.1')).toBe(false);
    expect(isAsyncapiSourceFormat('graphql')).toBe(false);
    expect(isAsyncapiSourceFormat(null)).toBe(false);
    expect(isAsyncapiSourceFormat(undefined)).toBe(false);
  });
});
