/**
 * Admin sign-up policy proxy (SGN-1.4, #5653).
 *
 * Behavioral tests for the server-side forwarders (`lib/auth/admin-signup-policy-proxy.ts`) —
 * upstream URL/headers, verbatim passthrough, transport-failure shaping and the policy-cache
 * invalidation on a successful save — plus source-level contract checks on the Next.js route
 * (session gate, handlers exported), following the auth-provider proxy tests.
 */
import * as fs from 'fs';
import * as path from 'path';

jest.mock('../../lib/auth/signup-policy-resolver', () => ({
  invalidateSignupPolicyCache: jest.fn(),
}));
jest.mock('../../lib/auth/provider-config-resolver', () => ({
  invalidateProviderConfigCache: jest.fn(),
}));

import {
  proxyGetSignupPolicy,
  proxyUpdateSignupPolicy,
} from '../../lib/auth/admin-signup-policy-proxy';
import { invalidateSignupPolicyCache } from '../../lib/auth/signup-policy-resolver';

const TOKEN = 'payload.signature';
const VIEW = {
  mode: 'invite_only',
  allowed_email_domains: [],
  source: 'db',
  env_mode: 'open',
  updated_at: '2026-10-11T00:00:00Z',
  updated_by: 'admin',
};

/** Build a minimal fetch-response stand-in for the pieces the proxy reads. */
function fakeResponse(status: number, body: unknown) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('proxyGetSignupPolicy', () => {
  it('targets the REST admin surface with the session header and passes the body through', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(fakeResponse(200, VIEW));

    const result = await proxyGetSignupPolicy(TOKEN, fetchImpl as unknown as typeof fetch);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://localhost:8000/v1/admin/signup-policy');
    expect(init.method).toBe('GET');
    expect(init.cache).toBe('no-store');
    expect(init.headers['X-Admin-Session']).toBe(TOKEN);
    expect(result).toEqual({ status: 200, body: VIEW });
    expect(invalidateSignupPolicyCache).not.toHaveBeenCalled();
  });

  it('shapes a transport failure as a 502', async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    const result = await proxyGetSignupPolicy(TOKEN, fetchImpl as unknown as typeof fetch);
    expect(result.status).toBe(502);
    expect(result.body).toMatchObject({ error: 'rest_unreachable' });
  });
});

describe('proxyUpdateSignupPolicy', () => {
  it('relays the payload verbatim and drops the policy cache on success', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(fakeResponse(200, VIEW));
    const payload = { mode: 'invite_only' as const, allowed_email_domains: [] };

    const result = await proxyUpdateSignupPolicy(
      TOKEN,
      payload,
      fetchImpl as unknown as typeof fetch,
    );

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://localhost:8000/v1/admin/signup-policy');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(result).toEqual({ status: 200, body: VIEW });
    expect(invalidateSignupPolicyCache).toHaveBeenCalledTimes(1);
  });

  it('relays a clear (mode: null) the same way', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(fakeResponse(200, { ...VIEW, source: 'env' }));
    await proxyUpdateSignupPolicy(
      TOKEN,
      { mode: null, allowed_email_domains: [] },
      fetchImpl as unknown as typeof fetch,
    );
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body).mode).toBeNull();
    expect(invalidateSignupPolicyCache).toHaveBeenCalledTimes(1);
  });

  it.each([401, 403, 422, 502])('keeps the cache on a %d', async (status) => {
    const fetchImpl = jest.fn().mockResolvedValue(fakeResponse(status, { detail: 'nope' }));
    const result = await proxyUpdateSignupPolicy(
      TOKEN,
      { mode: 'closed', allowed_email_domains: [] },
      fetchImpl as unknown as typeof fetch,
    );
    expect(result.status).toBe(status);
    expect(invalidateSignupPolicyCache).not.toHaveBeenCalled();
  });
});

describe('route file contract', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '../../src/app/api/admin/signup-policy/route.ts'),
    'utf8',
  );

  it('exports GET and PUT', () => {
    expect(source).toMatch(/export async function GET\(/);
    expect(source).toMatch(/export async function PUT\(/);
  });

  it('verifies the signed admin session before forwarding', () => {
    expect(source).toContain("cookieStore.get('admin_session')");
    expect(source).toContain('verifyAdminSessionToken(token)');
    expect(source).toContain('status: 401');
    expect(source).toContain('status: 403');
  });
});
