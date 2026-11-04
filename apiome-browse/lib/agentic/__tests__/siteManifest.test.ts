/**
 * Tests for the tenant agentic-web site manifests Browse serves — MFX-32.3 (#4297).
 *
 * Pins the site root (origin + base path), the REST URL (encoded slug, `site_url`), the
 * pass-through of the body with its content type and cache policy, and the error mapping
 * (404 passed on, any other failure a 502 so a crawler never caches an error as a manifest).
 */

import { describe, expect, it, vi } from 'vitest';
import {
  SITE_MANIFEST_CACHE_CONTROL,
  serveSiteManifest,
  serverRestApiBaseUrl,
  siteManifestRestUrl,
  siteRoot,
} from '../siteManifest';

const REST = 'http://rest.internal:8000/v1';

describe('serverRestApiBaseUrl', () => {
  it('prefers the internal address, then the public one, then the local default', () => {
    expect(
      serverRestApiBaseUrl({
        APIOME_REST_INTERNAL_BASE_URL: 'http://rest:8000/v1',
        NEXT_PUBLIC_REST_API_BASE_URL: 'https://api.example.com/v1',
      })
    ).toBe('http://rest:8000/v1');
    expect(serverRestApiBaseUrl({ NEXT_PUBLIC_REST_API_BASE_URL: 'https://api.example.com/v1' })).toBe(
      'https://api.example.com/v1'
    );
    expect(serverRestApiBaseUrl({})).toBe('http://localhost:8000/v1');
  });
});

describe('siteRoot', () => {
  it('is the request origin plus the base path, without a trailing slash', () => {
    expect(siteRoot('https://browse.example.com/tenant/acme/agents.json?x=1', '')).toBe(
      'https://browse.example.com'
    );
    expect(siteRoot('https://example.com:8443/apis/tenant/acme/llms.txt', '/apis/')).toBe(
      'https://example.com:8443/apis'
    );
  });
});

describe('siteManifestRestUrl', () => {
  it('encodes the tenant and passes the site root', () => {
    const url = siteManifestRestUrl('agents.json', 'ac me', 'https://browse.example.com', `${REST}/`);
    expect(url).toBe(
      'http://rest.internal:8000/v1/browse/tenants/ac%20me/agents.json?site_url=https%3A%2F%2Fbrowse.example.com'
    );
    expect(siteManifestRestUrl('llms.txt', 'acme', 'https://b.example.com', REST)).toContain(
      '/browse/tenants/acme/llms.txt?'
    );
  });
});

describe('serveSiteManifest', () => {
  const request = 'https://browse.example.com/tenant/acme/agents.json';

  it('passes the manifest through with its content type and cache policy', async () => {
    const fetchImpl = vi.fn(async () => new Response('{"site":{}}\n', { status: 200 }));
    const response = await serveSiteManifest('agents.json', 'acme', request, {
      restApiBaseUrl: REST,
      basePath: '',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(response.status).toBe(200);
    expect(await response.text()).toBe('{"site":{}}\n');
    expect(response.headers.get('content-type')).toBe('application/json; charset=utf-8');
    expect(response.headers.get('cache-control')).toBe(SITE_MANIFEST_CACHE_CONTROL);
    expect(fetchImpl).toHaveBeenCalledWith(
      `${REST}/browse/tenants/acme/agents.json?site_url=https%3A%2F%2Fbrowse.example.com`,
      { headers: { Accept: 'application/json' } }
    );
  });

  it('serves llms.txt as plain text', async () => {
    const fetchImpl = vi.fn(async () => new Response('# Acme\n', { status: 200 }));
    const response = await serveSiteManifest('llms.txt', 'acme', request, {
      restApiBaseUrl: REST,
      basePath: '/apis',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(response.headers.get('content-type')).toBe('text/plain; charset=utf-8');
    expect(String((fetchImpl.mock.calls[0] as unknown[])[0])).toContain('site_url=https%3A%2F%2Fbrowse.example.com%2Fapis');
  });

  it('passes on a 404 for an unknown tenant', async () => {
    const fetchImpl = vi.fn(async () => new Response('nope', { status: 404 }));
    const response = await serveSiteManifest('agents.json', 'nope', request, {
      restApiBaseUrl: REST,
      basePath: '',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(response.status).toBe(404);
  });

  it.each([
    ['an upstream error', async () => new Response('boom', { status: 500 })],
    ['an unreachable API', async () => {
      throw new Error('ECONNREFUSED');
    }],
  ])('answers 502 for %s, never caching it', async (_label, impl) => {
    const response = await serveSiteManifest('llms.txt', 'acme', request, {
      restApiBaseUrl: REST,
      basePath: '',
      fetchImpl: vi.fn(impl) as unknown as typeof fetch,
    });
    expect(response.status).toBe(502);
    expect(response.headers.get('cache-control')).toBeNull();
  });
});
