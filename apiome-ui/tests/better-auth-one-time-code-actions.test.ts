/**
 * Tests for the OLO-10.13 one-time-code sign-in server action (`better-auth-one-time-code-actions.ts`).
 *
 * The action bridges the browser's code-only sign-in onto the Better Auth engine: it redeems the code
 * through the `auth.api.verifyOneTimeCode` endpoint (which creates the session + sets the session
 * cookie) and then writes the app-owned last-active-tenant cookie for the pending tenant the endpoint
 * returns. Both the auth instance and `next/headers` are mocked so this stays a hermetic unit test.
 */

const mockVerifyOneTimeCode = jest.fn();
const mockCookieSet = jest.fn();
const mockCookies = jest.fn(async () => ({ set: mockCookieSet }));
const mockHeaders = jest.fn(async () => new Headers({ 'x-test': '1' }));

jest.mock('next/headers', () => ({
  cookies: (...args: unknown[]) => mockCookies(...args),
  headers: (...args: unknown[]) => mockHeaders(...args),
}));
jest.mock('@lib/auth/auth', () => ({
  auth: { api: { verifyOneTimeCode: mockVerifyOneTimeCode } },
}));

import { completeOneTimeCodeSignIn } from '@lib/auth/better-auth-one-time-code-actions';
import { LAST_ACTIVE_TENANT_COOKIE } from '@lib/auth/last-active-tenant';

const VALID_TENANT_ID = '11111111-2222-3333-4444-555555555555';

describe('completeOneTimeCodeSignIn', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('redeems the code and seeds the last-active-tenant cookie on success', async () => {
    mockVerifyOneTimeCode.mockResolvedValue({ ok: true, tenantId: VALID_TENANT_ID });

    const result = await completeOneTimeCodeSignIn('  code-123  ');

    expect(result).toEqual({ ok: true });
    // Code is trimmed and forwarded with the request headers so the endpoint can create the session.
    expect(mockVerifyOneTimeCode).toHaveBeenCalledWith(
      expect.objectContaining({ body: { oneTimeCode: 'code-123' } })
    );
    expect(mockVerifyOneTimeCode.mock.calls[0][0].headers).toBeInstanceOf(Headers);
    // The pending tenant is persisted to the durable cookie.
    expect(mockCookieSet).toHaveBeenCalledWith(
      LAST_ACTIVE_TENANT_COOKIE,
      VALID_TENANT_ID,
      expect.objectContaining({ httpOnly: true, sameSite: 'lax', path: '/' })
    );
  });

  it('establishes the session but writes no tenant cookie when the code carried none', async () => {
    mockVerifyOneTimeCode.mockResolvedValue({ ok: true, tenantId: null });

    const result = await completeOneTimeCodeSignIn('code-123');

    expect(result).toEqual({ ok: true });
    expect(mockCookieSet).not.toHaveBeenCalled();
  });

  it('does not write a malformed tenant id to the cookie', async () => {
    mockVerifyOneTimeCode.mockResolvedValue({ ok: true, tenantId: 'not-a-uuid' });

    const result = await completeOneTimeCodeSignIn('code-123');

    expect(result).toEqual({ ok: true });
    expect(mockCookieSet).not.toHaveBeenCalled();
  });

  it('fails closed (no tenant cookie) when the endpoint rejects the code', async () => {
    mockVerifyOneTimeCode.mockRejectedValue(new Error('Invalid or expired one-time code'));

    const result = await completeOneTimeCodeSignIn('bad-code');

    expect(result).toEqual({ ok: false });
    expect(mockCookieSet).not.toHaveBeenCalled();
  });

  it('rejects an empty code without hitting the endpoint', async () => {
    const result = await completeOneTimeCodeSignIn('   ');

    expect(result).toEqual({ ok: false });
    expect(mockVerifyOneTimeCode).not.toHaveBeenCalled();
  });
});
