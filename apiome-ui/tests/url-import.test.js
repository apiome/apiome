/**
 * URL Import Tests
 *
 * Comprehensive tests for URL import functionality in src/app/utils/url-import.ts
 * Tests all exported functions including:
 * - URL validation
 * - Authentication header building
 * - URL accessibility testing
 * - Specification fetching
 */

// Mock global fetch before importing module
const mockFetch = jest.fn();
global.fetch = mockFetch;

// We need to import dynamically after mocking
let validateImportUrl;
let fetchSpecificationFromUrl;
let testUrlAccessibility;

beforeAll(async () => {
  const module = await import('../src/app/utils/url-import');
  validateImportUrl = module.validateImportUrl;
  fetchSpecificationFromUrl = module.fetchSpecificationFromUrl;
  testUrlAccessibility = module.testUrlAccessibility;
});

describe('URL Import - validateImportUrl', () => {
  test('should reject empty URL', () => {
    const result = validateImportUrl('');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('empty');
  });

  test('should reject whitespace-only URL', () => {
    const result = validateImportUrl('   ');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('empty');
  });

  test('should accept valid HTTP URL', () => {
    const result = validateImportUrl('http://api.example.com/openapi.yaml');
    expect(result.valid).toBe(true);
    expect(result.error).toBeUndefined();
  });

  test('should accept valid HTTPS URL', () => {
    const result = validateImportUrl('https://api.example.com/openapi.yaml');
    expect(result.valid).toBe(true);
    expect(result.error).toBeUndefined();
  });

  test('should reject FTP URL', () => {
    const result = validateImportUrl('ftp://api.example.com/openapi.yaml');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('HTTP');
  });

  test('should reject file URL', () => {
    const result = validateImportUrl('file:///path/to/openapi.yaml');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('HTTP');
  });

  test('should reject invalid URL format', () => {
    const result = validateImportUrl('not-a-valid-url');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('Invalid URL');
  });

  test('should accept URL with query parameters', () => {
    const result = validateImportUrl('https://api.example.com/openapi.yaml?version=2');
    expect(result.valid).toBe(true);
  });

  test('should accept URL with port', () => {
    const result = validateImportUrl('https://api.example.com:8080/openapi.yaml');
    expect(result.valid).toBe(true);
  });

  test('should accept localhost URLs', () => {
    const result = validateImportUrl('http://localhost:3000/openapi.yaml');
    expect(result.valid).toBe(true);
  });

  test('should accept IP address URLs', () => {
    const result = validateImportUrl('http://192.168.1.1:8080/openapi.yaml');
    expect(result.valid).toBe(true);
  });
});

describe('URL Import - fetchSpecificationFromUrl', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  test('should return error for invalid URL', async () => {
    const result = await fetchSpecificationFromUrl({ url: '' });
    expect(result.success).toBe(false);
    expect(result.error).toBeDefined();
  });

  test('should fetch specification successfully', async () => {
    const mockSpec = `openapi: "3.1.0"
info:
  title: Test API
  version: "1.0.0"
paths: {}`;

    const mockHeaders = new Headers();
    mockHeaders.set('content-type', 'application/yaml');
    mockHeaders.set('content-disposition', 'attachment; filename="openapi.yaml"');

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: () => Promise.resolve(mockSpec),
      headers: mockHeaders
    });

    const result = await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.success).toBe(true);
    expect(result.content).toBe(mockSpec);
    expect(result.statusCode).toBe(200);
  });

  test('should handle HTTP error response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found'
    });

    const result = await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.success).toBe(false);
    expect(result.statusCode).toBe(404);
    expect(result.error).toContain('404');
  });

  test('should handle empty response', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve(''),
      headers: mockHeaders
    });

    const result = await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.success).toBe(false);
    expect(result.error).toContain('Empty response');
  });

  test('should handle network error', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    const result = await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.success).toBe(false);
    expect(result.error).toContain('Network error');
  });

  test('should add bearer token header', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve('openapi: "3.1.0"'),
      headers: mockHeaders
    });

    await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml',
      authType: 'bearer',
      authToken: 'my-secret-token'
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.example.com/openapi.yaml',
      expect.objectContaining({
        headers: expect.objectContaining({
          'Authorization': 'Bearer my-secret-token'
        })
      })
    );
  });

  test('should add API key header', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve('openapi: "3.1.0"'),
      headers: mockHeaders
    });

    await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml',
      authType: 'apiKey',
      authToken: 'my-api-key',
      apiKeyHeader: 'X-Custom-Key'
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.example.com/openapi.yaml',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Custom-Key': 'my-api-key'
        })
      })
    );
  });

  test('should add basic auth header', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve('openapi: "3.1.0"'),
      headers: mockHeaders
    });

    await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml',
      authType: 'basic',
      username: 'user',
      password: 'pass'
    });

    const expectedBasicAuth = 'Basic ' + Buffer.from('user:pass').toString('base64');

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'Authorization': expectedBasicAuth
        })
      })
    );
  });

  test('should follow redirects by default', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve('openapi: "3.1.0"'),
      headers: mockHeaders
    });

    await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        redirect: 'follow'
      })
    );
  });

  test('should not follow redirects when disabled', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve('openapi: "3.1.0"'),
      headers: mockHeaders
    });

    await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml',
      followRedirects: false
    });

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        redirect: 'manual'
      })
    );
  });
});

describe('URL Import - testUrlAccessibility', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  test('should return error for invalid URL', async () => {
    const result = await testUrlAccessibility({ url: '' });
    expect(result.accessible).toBe(false);
    expect(result.error).toBeDefined();
  });

  test('should return accessible for 200 response', async () => {
    const mockHeaders = new Headers();
    mockHeaders.set('content-type', 'application/yaml');

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: mockHeaders
    });

    const result = await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.accessible).toBe(true);
    expect(result.statusCode).toBe(200);
  });

  test('should return not accessible for 404 response', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      headers: mockHeaders
    });

    const result = await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.accessible).toBe(false);
    expect(result.statusCode).toBe(404);
    expect(result.error).toContain('404');
  });

  test('should return not accessible for 401 response', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      headers: mockHeaders
    });

    const result = await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.accessible).toBe(false);
    expect(result.statusCode).toBe(401);
  });

  test('should fall back to GET if HEAD returns 405', async () => {
    const mockHeaders = new Headers();
    mockHeaders.set('content-type', 'application/yaml');

    // First call (HEAD) returns 405
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 405,
      statusText: 'Method Not Allowed',
      headers: mockHeaders
    });

    // Second call (GET) returns 200
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: mockHeaders
    });

    const result = await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.accessible).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  test('should handle network error', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    const result = await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.accessible).toBe(false);
    expect(result.error).toContain('Network error');
  });

  test('should use HEAD method for testing', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: mockHeaders
    });

    await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'HEAD'
      })
    );
  });

  test('should include auth headers when provided', async () => {
    const mockHeaders = new Headers();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: mockHeaders
    });

    await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml',
      authType: 'bearer',
      authToken: 'my-token'
    });

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'Authorization': 'Bearer my-token'
        })
      })
    );
  });

  test('should return content type from response', async () => {
    const mockHeaders = new Headers();
    mockHeaders.set('content-type', 'application/x-yaml');

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: mockHeaders
    });

    const result = await testUrlAccessibility({
      url: 'https://api.example.com/openapi.yaml'
    });

    expect(result.contentType).toBe('application/x-yaml');
  });
});

console.log('✅ URL Import tests defined - comprehensive coverage!');

describe('URL Import - cache behavior', () => {
  let storageMock;

  beforeEach(() => {
    mockFetch.mockClear();
    // Fresh in-memory sessionStorage mock for each test
    const store = {};
    storageMock = {
      getItem: jest.fn((key) => store[key] ?? null),
      setItem: jest.fn((key, value) => { store[key] = String(value); }),
      removeItem: jest.fn((key) => { delete store[key]; }),
    };
    Object.defineProperty(global, 'sessionStorage', { value: storageMock, writable: true });
  });

  const CACHE_KEY = 'apiome:url-import-cache:v1';

  const mockYamlHeaders = () => {
    const h = new Headers();
    h.set('content-type', 'application/yaml');
    return h;
  };

  const mockYamlFetch = (content = 'openapi: "3.1.0"') => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: () => Promise.resolve(content),
      headers: mockYamlHeaders(),
    });
  };

  test('cache miss: fetch is called when cache is empty', async () => {
    mockYamlFetch();
    const result = await fetchSpecificationFromUrl({
      url: 'https://api.example.com/openapi.yaml',
      useCache: true,
    });
    expect(result.success).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  test('cache hit: fetch is skipped on second call with same URL and auth', async () => {
    mockYamlFetch();
    const opts = { url: 'https://api.example.com/openapi.yaml', useCache: true };

    await fetchSpecificationFromUrl(opts);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    mockFetch.mockClear();
    const result = await fetchSpecificationFromUrl(opts);
    expect(result.success).toBe(true);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  test('cache returns stored contentType on hit', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: () => Promise.resolve('{"openapi":"3.1.0"}'),
      headers: (() => { const h = new Headers(); h.set('content-type', 'application/json'); return h; })(),
    });
    const opts = { url: 'https://api.example.com/openapi.json', useCache: true };
    await fetchSpecificationFromUrl(opts);

    mockFetch.mockClear();
    const result = await fetchSpecificationFromUrl(opts);
    expect(result.success).toBe(true);
    expect(result.contentType).toBe('application/json');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  test('cache miss after TTL expiry: fetch is called again', async () => {
    mockYamlFetch();
    const opts = { url: 'https://api.example.com/openapi.yaml', useCache: true };
    await fetchSpecificationFromUrl(opts);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Expire the cache entry by back-dating storedAt
    const raw = storageMock.getItem(CACHE_KEY);
    const store = JSON.parse(raw);
    const keys = Object.keys(store);
    expect(keys.length).toBeGreaterThan(0);
    const [key] = keys;
    store[key].storedAt = Date.now() - 25 * 60 * 60 * 1000; // 25 hours ago
    storageMock.setItem(CACHE_KEY, JSON.stringify(store));

    mockYamlFetch();
    mockFetch.mockClear();
    const result = await fetchSpecificationFromUrl(opts);
    expect(result.success).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  test('invalid storedAt is treated as expired', async () => {
    mockYamlFetch();
    const opts = { url: 'https://api.example.com/openapi.yaml', useCache: true };
    await fetchSpecificationFromUrl(opts);

    // Corrupt the storedAt field
    const raw = storageMock.getItem(CACHE_KEY);
    const store = JSON.parse(raw);
    const keys = Object.keys(store);
    expect(keys.length).toBeGreaterThan(0);
    const [key] = keys;
    store[key].storedAt = 'not-a-number';
    storageMock.setItem(CACHE_KEY, JSON.stringify(store));

    mockYamlFetch();
    mockFetch.mockClear();
    const result = await fetchSpecificationFromUrl(opts);
    expect(result.success).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  test('different auth settings produce separate cache entries', async () => {
    const url = 'https://api.example.com/openapi.yaml';

    mockYamlFetch();
    await fetchSpecificationFromUrl({ url, useCache: true, authType: 'bearer', authToken: 'token-a' });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Different token — should NOT hit cache for token-a
    mockYamlFetch();
    mockFetch.mockClear();
    await fetchSpecificationFromUrl({ url, useCache: true, authType: 'bearer', authToken: 'token-b' });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Same token-a again — should hit cache
    mockFetch.mockClear();
    const result = await fetchSpecificationFromUrl({ url, useCache: true, authType: 'bearer', authToken: 'token-a' });
    expect(result.success).toBe(true);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  test('no-auth and bearer-auth use separate cache entries for the same URL', async () => {
    const url = 'https://api.example.com/openapi.yaml';

    mockYamlFetch();
    await fetchSpecificationFromUrl({ url, useCache: true });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    mockYamlFetch();
    mockFetch.mockClear();
    await fetchSpecificationFromUrl({ url, useCache: true, authType: 'bearer', authToken: 'tok' });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});

