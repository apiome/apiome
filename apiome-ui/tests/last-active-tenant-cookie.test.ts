/**
 * The last-active-tenant cookie rides the shared cookie domain (BAA-2.2, apiome #6565).
 *
 * The session cookie is scoped to `BETTER_AUTH_COOKIE_DOMAIN` so a sign-in on the main app is a
 * sign-in on the studio. The tenant hint that qualifies it used to be written host-only, so the two
 * origins read one session but derived different active tenants. These cases pin that every writer
 * uses the one options builder, and that the builder scopes the cookie exactly as the session
 * cookie is scoped: to the shared domain in production, host-only otherwise.
 */

const mockSet = jest.fn();
const mockDomain = jest.fn<string | undefined, []>();

jest.mock('next/headers', () => ({
  cookies: jest.fn(async () => ({ set: mockSet, delete: jest.fn() })),
}));
jest.mock('@lib/auth/cookie-options', () => ({
  getSharedCookieDomain: () => mockDomain(),
}));
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => ({ user: { user_id: 'user-1' } })),
}));
jest.mock('@lib/auth/post-login-routing', () => ({
  validateTenantSwitch: jest.fn(async (_userId: string, tenantId: string) => tenantId),
}));

import {
  LAST_ACTIVE_TENANT_COOKIE,
  LAST_ACTIVE_TENANT_MAX_AGE_SECONDS,
  lastActiveTenantCookieOptions,
} from '@lib/auth/last-active-tenant';
import { persistLastActiveTenant, setActiveTenant } from '@lib/auth/last-active-tenant-actions';

const TENANT_ID = '11111111-2222-3333-4444-555555555555';
const savedNodeEnv = process.env.NODE_ENV;

function setNodeEnv(value: string | undefined): void {
  if (value === undefined) delete (process.env as Record<string, string | undefined>).NODE_ENV;
  else (process.env as Record<string, string | undefined>).NODE_ENV = value;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockDomain.mockReturnValue(undefined);
});

afterEach(() => {
  setNodeEnv(savedNodeEnv);
});

describe('lastActiveTenantCookieOptions', () => {
  it('scopes the cookie to the shared domain the session cookie uses', () => {
    setNodeEnv('production');
    mockDomain.mockReturnValue('.apiome.dev');

    expect(lastActiveTenantCookieOptions()).toEqual({
      httpOnly: true,
      sameSite: 'lax',
      secure: true,
      path: '/',
      maxAge: LAST_ACTIVE_TENANT_MAX_AGE_SECONDS,
      domain: '.apiome.dev',
    });
  });

  it('stays host-only when no shared domain resolves (development, localhost)', () => {
    setNodeEnv('development');

    const options = lastActiveTenantCookieOptions();

    expect(options).not.toHaveProperty('domain');
    expect(options.secure).toBe(false);
  });

  it('never restates the lifetime', () => {
    expect(lastActiveTenantCookieOptions().maxAge).toBe(60 * 60 * 24 * 180);
  });
});

describe('the writers', () => {
  it('setActiveTenant writes the domain-scoped cookie', async () => {
    mockDomain.mockReturnValue('.apiome.dev');

    await expect(setActiveTenant(TENANT_ID)).resolves.toBe(TENANT_ID);

    expect(mockSet).toHaveBeenCalledWith(
      LAST_ACTIVE_TENANT_COOKIE,
      TENANT_ID,
      expect.objectContaining({ domain: '.apiome.dev', path: '/', httpOnly: true, sameSite: 'lax' })
    );
  });

  it('persistLastActiveTenant writes the domain-scoped cookie', async () => {
    mockDomain.mockReturnValue('.apiome.dev');

    await persistLastActiveTenant(TENANT_ID);

    expect(mockSet).toHaveBeenCalledWith(
      LAST_ACTIVE_TENANT_COOKIE,
      TENANT_ID,
      expect.objectContaining({ domain: '.apiome.dev' })
    );
  });

  it('writes host-only when there is no shared domain', async () => {
    await setActiveTenant(TENANT_ID);

    const [, , options] = mockSet.mock.calls[0];
    expect(options).not.toHaveProperty('domain');
  });

  it('still refuses a malformed id before touching the cookie', async () => {
    mockDomain.mockReturnValue('.apiome.dev');

    await expect(setActiveTenant('not-a-uuid')).resolves.toBeNull();
    await persistLastActiveTenant('not-a-uuid');

    expect(mockSet).not.toHaveBeenCalled();
  });
});
