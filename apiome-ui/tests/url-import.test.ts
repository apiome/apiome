/**
 * URL Import Cache Tests (TypeScript)
 *
 * Covers cache hit/miss, TTL expiry, invalid storedAt, and auth-keyed isolation.
 * The broader functional tests live in url-import.test.js.
 */

import { fetchSpecificationFromUrl } from '../src/app/utils/url-import';

const mockFetch = jest.fn();
(global as unknown as Record<string, unknown>).fetch = mockFetch;

const CACHE_KEY = 'apiome:url-import-cache:v1';

function buildSessionStorageMock() {
  const store: Record<string, string> = {};
  return {
    getItem: jest.fn((key: string) => store[key] ?? null),
    setItem: jest.fn((key: string, value: string) => { store[key] = String(value); }),
    removeItem: jest.fn((key: string) => { delete store[key]; }),
  };
}

function mockYamlFetch(content = 'openapi: "3.1.0"') {
  const h = new Headers();
  h.set('content-type', 'application/yaml');
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: () => Promise.resolve(content),
    headers: h,
  });
}

describe('URL Import - cache behavior', () => {
  let storageMock: ReturnType<typeof buildSessionStorageMock>;

  beforeEach(() => {
    mockFetch.mockClear();
    storageMock = buildSessionStorageMock();
    Object.defineProperty(global, 'sessionStorage', { value: storageMock, writable: true, configurable: true });
  });

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
    const jsonHeaders = new Headers();
    jsonHeaders.set('content-type', 'application/json');
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: () => Promise.resolve('{"openapi":"3.1.0"}'),
      headers: jsonHeaders,
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

    // Expire the cache by back-dating storedAt
    const raw = storageMock.getItem(CACHE_KEY);
    const cacheStore = JSON.parse(raw as string);
    const keys = Object.keys(cacheStore);
    expect(keys.length).toBeGreaterThan(0);
    const key = keys[0];
    cacheStore[key].storedAt = Date.now() - 25 * 60 * 60 * 1000; // 25 hours ago
    storageMock.setItem(CACHE_KEY, JSON.stringify(cacheStore));

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

    // Corrupt storedAt
    const raw = storageMock.getItem(CACHE_KEY);
    const cacheStore = JSON.parse(raw as string);
    const keys = Object.keys(cacheStore);
    expect(keys.length).toBeGreaterThan(0);
    const key = keys[0];
    (cacheStore[key] as Record<string, unknown>).storedAt = 'not-a-number';
    storageMock.setItem(CACHE_KEY, JSON.stringify(cacheStore));

    mockYamlFetch();
    mockFetch.mockClear();
    const result = await fetchSpecificationFromUrl(opts);
    expect(result.success).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  test('different auth tokens produce separate cache entries', async () => {
    const url = 'https://api.example.com/openapi.yaml';

    mockYamlFetch();
    await fetchSpecificationFromUrl({ url, useCache: true, authType: 'bearer', authToken: 'token-a' });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Different token — should NOT hit cache
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

