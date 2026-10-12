/**
 * @jest-environment node
 *
 * The link-initiation route, `POST /api/auth/link/[provider]` (OLO-7.3 follow-up, #4963).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * As a GET with no Origin check, a cross-site top-level navigation carried the visitor's
 * `SameSite=lax` session and primed an `oauth_link_intent` cookie for them. These tests drive the
 * real handler and pin the fix: the route is POST-only, and a request that does not come from this
 * app's own pages is refused before the session is even read.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({ getAuthSession: jest.fn() }));
jest.mock('@lib/auth/provider-config-resolver', () => ({ resolveProviderEnv: jest.fn(async () => ({})) }));
jest.mock('@lib/auth/provider-registry', () => ({ isProviderEnabled: jest.fn() }));
jest.mock('@lib/auth/login-rate-limit', () => ({
  AUTH_RATE_LIMITED_CODE: 'auth-rate-limited',
  checkRequestBudget: jest.fn(),
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { isProviderEnabled } from '@lib/auth/provider-registry';
import { checkRequestBudget } from '@lib/auth/login-rate-limit';
import * as linkRoute from '@/app/api/auth/link/[provider]/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockEnabled = isProviderEnabled as unknown as jest.Mock;
const mockBudget = checkRequestBudget as unknown as jest.Mock;

const HOST = 'app.apiome.dev';
const USER_ID = '660e8400-e29b-41d4-a716-446655440001';

/** Call the handler as a browser on `origin` would (omit `origin` for a request that sends none). */
const post = (provider: string, origin?: string) =>
  linkRoute.POST(
    new NextRequest(`https://${HOST}/api/auth/link/${provider}`, {
      method: 'POST',
      headers: { host: HOST, ...(origin ? { origin } : {}) },
    }),
    { params: Promise.resolve({ provider }) }
  );

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: { user_id: USER_ID } });
  mockEnabled.mockReturnValue(true);
  mockBudget.mockReturnValue({ allowed: true, retryAfterMs: 0 });
});

describe('POST /api/auth/link/[provider]', () => {
  test('is the only method the route answers — a GET is not routed', () => {
    expect(Object.keys(linkRoute).filter((name) => /^[A-Z]+$/.test(name))).toEqual(['POST']);
  });

  test('sets the link-intent cookie for a same-origin request', async () => {
    const response = await post('github', `https://${HOST}`);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ success: true, provider: 'github' });

    const cookie = response.cookies.get('oauth_link_intent');
    expect(JSON.parse(cookie?.value ?? '{}')).toMatchObject({ userId: USER_ID, provider: 'github' });
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'lax', path: '/' });
  });

  test.each([
    ['another site', 'https://evil.example'],
    ['a sibling subdomain', 'https://suite.apiome.dev'],
    ['an opaque origin', 'null'],
    ['no Origin header at all', undefined],
  ])('refuses %s with 403, before the session is read and without a cookie', async (_name, origin) => {
    const response = await post('github', origin);
    expect(response.status).toBe(403);
    expect(response.cookies.get('oauth_link_intent')).toBeUndefined();
    expect(mockSession).not.toHaveBeenCalled();
  });

  test('still spends the per-IP budget on a cross-site request, so floods stay cheap', async () => {
    mockBudget.mockReturnValueOnce({ allowed: false, retryAfterMs: 5000 });
    const response = await post('github', 'https://evil.example');
    expect(response.status).toBe(429);
    expect(response.headers.get('Retry-After')).toBe('5');
  });

  test('requires a session', async () => {
    mockSession.mockResolvedValue(null);
    const response = await post('github', `https://${HOST}`);
    expect(response.status).toBe(401);
    expect(response.cookies.get('oauth_link_intent')).toBeUndefined();
  });

  test('refuses a provider this deployment cannot link', async () => {
    mockEnabled.mockReturnValue(false);
    const response = await post('github', `https://${HOST}`);
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ code: 'provider-not-configured' });
    expect(response.cookies.get('oauth_link_intent')).toBeUndefined();
  });
});
