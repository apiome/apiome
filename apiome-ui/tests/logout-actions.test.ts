/**
 * Unit tests for the deterministic server-side logout (serverLogout).
 *
 * Guards the fix for the "logout leaves the account signed in" bug: the session
 * cookie must be force-expired server-side (host-only, plus domain-scoped when a
 * shared cookie domain is configured), and the durable last-active-tenant cookie
 * must be cleared so the next login does not silently restore the old tenant.
 */

import { LAST_ACTIVE_TENANT_COOKIE } from '@lib/auth/last-active-tenant';

const mockDelete = jest.fn();
const mockSet = jest.fn();

jest.mock('next/headers', () => ({
  cookies: jest.fn(async () => ({ set: mockSet, delete: mockDelete })),
}));

jest.mock('@lib/auth/cookie-options', () => ({
  getSharedCookieDomain: jest.fn(),
}));

import { serverLogout } from '@lib/auth/logout-actions';
import { getSharedCookieDomain } from '@lib/auth/cookie-options';

const SESSION_NAMES = [
  'next-auth.session-token',
  '__Secure-next-auth.session-token',
  '__Host-next-auth.session-token',
];

describe('serverLogout', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('deletes the durable last-active-tenant cookie', async () => {
    (getSharedCookieDomain as jest.Mock).mockReturnValue(undefined);
    await serverLogout();
    expect(mockDelete).toHaveBeenCalledWith(LAST_ACTIVE_TENANT_COOKIE);
  });

  it('host-only expires every session-cookie variant when no shared domain', async () => {
    (getSharedCookieDomain as jest.Mock).mockReturnValue(undefined);
    await serverLogout();

    for (const name of SESSION_NAMES) {
      expect(mockSet).toHaveBeenCalledWith(
        name,
        '',
        expect.objectContaining({ path: '/', maxAge: 0, httpOnly: true, sameSite: 'lax' }),
      );
    }
    // No domain-scoped variant emitted when there is no shared domain.
    const domainCalls = mockSet.mock.calls.filter(([, , opts]) => 'domain' in (opts ?? {}));
    expect(domainCalls).toHaveLength(0);
  });

  it('also domain-scopes the expiry for shareable cookies, but never for __Host-', async () => {
    (getSharedCookieDomain as jest.Mock).mockReturnValue('.apiome.dev');
    await serverLogout();

    // Domain variant for the unprefixed + __Secure- names.
    expect(mockSet).toHaveBeenCalledWith(
      'next-auth.session-token',
      '',
      expect.objectContaining({ domain: '.apiome.dev', maxAge: 0 }),
    );
    expect(mockSet).toHaveBeenCalledWith(
      '__Secure-next-auth.session-token',
      '',
      expect.objectContaining({ domain: '.apiome.dev', maxAge: 0 }),
    );

    // __Host- cookies are host-locked and must never carry a Domain.
    const hostDomainCalls = mockSet.mock.calls.filter(
      ([name, , opts]) => name === '__Host-next-auth.session-token' && 'domain' in (opts ?? {}),
    );
    expect(hostDomainCalls).toHaveLength(0);
  });

  it('expires __Secure-/__Host- variants with Secure regardless of NODE_ENV', async () => {
    (getSharedCookieDomain as jest.Mock).mockReturnValue(undefined);
    await serverLogout();

    const secureCall = mockSet.mock.calls.find(
      ([name]) => name === '__Secure-next-auth.session-token',
    );
    expect(secureCall?.[2]).toMatchObject({ secure: true });
  });
});
