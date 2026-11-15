import { describe, expect, it, vi } from 'vitest';

import { exchangeToken, fetchReader, portalAuthUrl, requestMagicLink, serverRestBase, signOutReader } from '../api';

const REST = 'https://api.example/v1/';
const TOKEN = 'prs_' + 'b'.repeat(43);

function respond(status: number, body?: unknown, headers: Record<string, string> = {}) {
  return vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status, headers }));
}

describe('portalAuthUrl', () => {
  it('addresses the tenant under /portal', () => {
    expect(portalAuthUrl(REST, 'acme')).toBe('https://api.example/v1/portal/acme/auth');
  });
});

describe('requestMagicLink', () => {
  it('posts the address and return path and accepts the 202', async () => {
    const fetchImpl = respond(202, { accepted: true });
    expect(await requestMagicLink(REST, 'acme', 'ada@example.com', '/tenant/acme', fetchImpl)).toEqual({ ok: true });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.example/v1/portal/acme/auth/magic-link');
    expect(JSON.parse(String(init.body))).toEqual({ email: 'ada@example.com', return_to: '/tenant/acme' });
  });

  it('omits an empty return path', async () => {
    const fetchImpl = respond(202, { accepted: true });
    await requestMagicLink(REST, 'acme', 'ada@example.com', null, fetchImpl);
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ email: 'ada@example.com' });
  });

  it('reports the rate limit with its wait', async () => {
    const outcome = await requestMagicLink(REST, 'acme', 'a@b.io', null, respond(429, {}, { 'Retry-After': '42' }));
    expect(outcome).toEqual({ ok: false, kind: 'rate-limited', retryAfterSeconds: 42 });
  });

  it('passes on the server message for malformed input', async () => {
    const outcome = await requestMagicLink(
      REST,
      'acme',
      'nope',
      null,
      respond(422, { detail: { code: 'portal-invalid-email', message: 'Enter a valid email address.' } }),
    );
    expect(outcome).toEqual({ ok: false, kind: 'invalid', message: 'Enter a valid email address.' });
  });

  it('reads a network fault as unavailable', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('offline');
    });
    expect(await requestMagicLink(REST, 'acme', 'a@b.io', null, fetchImpl)).toEqual({ ok: false, kind: 'unavailable' });
  });
});

describe('exchangeToken', () => {
  it('returns the grant and forwards the reader user agent', async () => {
    const grant = { session_token: TOKEN, expires_at: '2026-11-21T12:00:00Z', reader: { email: 'ada@example.com' } };
    const fetchImpl = respond(200, grant);
    expect(await exchangeToken(REST, 'acme', 'pml_x', 'Firefox/132.0', fetchImpl)).toEqual({ ok: true, grant });
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)['User-Agent']).toBe('Firefox/132.0');
  });

  it.each([
    [410, 'portal-token-expired', 'expired'],
    [410, 'portal-token-used', 'used'],
    [400, 'portal-token-invalid', 'invalid'],
    [500, undefined, 'invalid'],
  ])('maps a %i %s to %s', async (status, code, reason) => {
    const outcome = await exchangeToken(REST, 'acme', 'pml_x', null, respond(status, { detail: { code } }));
    expect(outcome).toEqual({ ok: false, reason });
  });
});

describe('fetchReader / signOutReader', () => {
  it('reads the reader with the Reader header', async () => {
    const fetchImpl = respond(200, { email: 'ada@example.com' });
    expect(await fetchReader(REST, 'acme', TOKEN, fetchImpl)).toEqual({ email: 'ada@example.com' });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.example/v1/portal/acme/auth/me');
    expect((init.headers as Record<string, string>).Authorization).toBe(`Reader ${TOKEN}`);
  });

  it('returns null for a dead session', async () => {
    expect(await fetchReader(REST, 'acme', TOKEN, respond(401, {}))).toBeNull();
  });

  it('never throws on sign-out', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('offline');
    });
    await expect(signOutReader(REST, 'acme', TOKEN, fetchImpl)).resolves.toBeUndefined();
  });
});

describe('serverRestBase', () => {
  it('prefers the internal URL', () => {
    expect(serverRestBase({ APIOME_REST_INTERNAL_BASE_URL: 'http://rest:8000/v1', NEXT_PUBLIC_REST_API_BASE_URL: 'x' })).toBe(
      'http://rest:8000/v1',
    );
    expect(serverRestBase({ NEXT_PUBLIC_REST_API_BASE_URL: 'https://api.example/v1' })).toBe('https://api.example/v1');
    expect(serverRestBase({})).toBe('http://localhost:8000/v1');
  });
});
