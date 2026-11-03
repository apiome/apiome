/**
 * @jest-environment node
 *
 * The service bearer every server-side call to apiome-rest carries (BAA-2.3, apiome #6566).
 *
 * This module is the **one** implementation of the bearer: the private suite's `designer`
 * re-exports it rather than carrying a copy, so these cases pin a cross-service contract — the
 * algorithm, lifetime, signing secret and every claim in
 * `private-suite/docs/contracts/suite-auth-token.contract.json` — not an internal helper. A diff
 * that turns one of them red is a change `apiome-rest`, `spire` and the studio all have to agree to.
 *
 * Runs in the node environment: the signer is server-only code.
 */

import jwt from 'jsonwebtoken';

import {
  createRestAuthHeaders,
  getJwtSigningSecret,
  getRestApiBaseUrl,
  getRestJwtSigningSecret,
  resolveSessionPrincipalId,
  restSessionUser,
  REST_API_BASE_URL,
} from '@lib/rest-auth';
import { isSessionElevated } from '@lib/auth/session-elevation';

const CONTROLLED_KEYS = [
  'BETTER_AUTH_SECRET',
  'NEXTAUTH_SECRET',
  'REST_API_BASE_URL',
  'NEXT_PUBLIC_REST_API_BASE_URL',
] as const;

const SECRET = 'shared-with-the-studio-and-spire';
const USER_ID = 'de1e7e6e-0000-4000-8000-000000000001';
const TENANT_ID = '7e9a1c6e-0000-4000-8000-000000000002';

/** An `AppSession` as `getAuthSession()` returns it, with the 2FA marker under test. */
function appSession(twoFactorElevated: boolean | undefined, user: Record<string, unknown> = {}) {
  return {
    user: {
      user_id: USER_ID,
      email: 'dev@apiome.app',
      name: 'Dev',
      current_tenant_id: TENANT_ID,
      twoFactorEnabled: true,
      ...user,
    },
    expires: '2999-01-01T00:00:00.000Z',
    ...(twoFactorElevated === undefined ? {} : { twoFactorElevated }),
  };
}

/** Mint a bearer for a session and return its verified claims. */
function claimsFor(session: ReturnType<typeof appSession>, secret = SECRET): Record<string, unknown> {
  const headers = createRestAuthHeaders(restSessionUser(session));
  const token = headers.Authorization?.replace('Bearer ', '') ?? '';
  return jwt.verify(token, secret) as Record<string, unknown>;
}

describe('the apiome-rest service bearer (BAA-2.3)', () => {
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of CONTROLLED_KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
    process.env.BETTER_AUTH_SECRET = SECRET;
  });

  afterEach(() => {
    for (const key of CONTROLLED_KEYS) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
  });

  describe('the signing secret', () => {
    it('is BETTER_AUTH_SECRET, read through the Better Auth resolver', () => {
      expect(getRestJwtSigningSecret()).toBe(SECRET);
      expect(getJwtSigningSecret()).toBe(SECRET);
    });

    it('is never NEXTAUTH_SECRET', () => {
      delete process.env.BETTER_AUTH_SECRET;
      process.env.NEXTAUTH_SECRET = SECRET;

      expect(getRestJwtSigningSecret()).toBeUndefined();
      expect(createRestAuthHeaders(restSessionUser(appSession(false))).Authorization).toBeUndefined();
    });

    it('treats a blank secret as unset', () => {
      process.env.BETTER_AUTH_SECRET = '   ';

      expect(createRestAuthHeaders(restSessionUser(appSession(false)))).toEqual({
        'Content-Type': 'application/json',
      });
    });
  });

  describe('the claim set the contract file pins', () => {
    it('carries every agreed claim, snake_cased', () => {
      const claims = claimsFor(appSession(true));

      expect(claims).toMatchObject({
        sub: USER_ID,
        user_id: USER_ID,
        email: 'dev@apiome.app',
        name: 'Dev',
        current_tenant_id: TENANT_ID,
        two_factor_elevated: true,
      });
      expect(Object.keys(claims).sort()).toEqual([
        'current_tenant_id',
        'email',
        'exp',
        'iat',
        'name',
        'sub',
        'two_factor_elevated',
        'user_id',
      ]);
    });

    it('signs HS256 with a one-hour lifetime', () => {
      const headers = createRestAuthHeaders(restSessionUser(appSession(false)));
      const token = headers.Authorization?.replace('Bearer ', '') ?? '';
      const decoded = jwt.decode(token, { complete: true });

      expect(decoded?.header.alg).toBe('HS256');
      const payload = decoded?.payload as { iat: number; exp: number };
      expect(payload.exp - payload.iat).toBe(3600);
    });

    it('omits current_tenant_id for a tenant-less user rather than signing null', () => {
      const claims = claimsFor(appSession(false, { current_tenant_id: undefined }));

      expect(claims).not.toHaveProperty('current_tenant_id');
    });

    it('sends only Content-Type when the session carries no principal', () => {
      expect(createRestAuthHeaders({ user_id: '  ' })).toEqual({ 'Content-Type': 'application/json' });
      expect(createRestAuthHeaders({})).toEqual({ 'Content-Type': 'application/json' });
    });

    it('trims the principal it signs', () => {
      const claims = claimsFor(appSession(false, { user_id: `  ${USER_ID}  ` }));

      expect(claims.sub).toBe(USER_ID);
      expect(claims.user_id).toBe(USER_ID);
    });
  });

  describe('the 2FA-elevation marker (decision D8)', () => {
    it('propagates an elevated session as two_factor_elevated: true', () => {
      expect(claimsFor(appSession(true)).two_factor_elevated).toBe(true);
    });

    it('propagates a non-elevated session as false', () => {
      expect(claimsFor(appSession(false)).two_factor_elevated).toBe(false);
    });

    it('defaults to false when the session carries no marker at all', () => {
      expect(claimsFor(appSession(undefined)).two_factor_elevated).toBe(false);
    });

    it('never derives elevation from the account-level twoFactorEnabled flag', () => {
      expect(claimsFor(appSession(false, { twoFactorEnabled: true })).two_factor_elevated).toBe(false);
      expect(claimsFor(appSession(true, { twoFactorEnabled: false })).two_factor_elevated).toBe(true);
    });

    it('signs false, not a passthrough, when a bare user is handed to the signer', () => {
      // The fold happens in restSessionUser(); a caller that skips it gets a definite false, never
      // an absent claim that a verifier might read differently.
      const headers = createRestAuthHeaders(appSession(true).user);
      const token = headers.Authorization?.replace('Bearer ', '') ?? '';

      expect((jwt.verify(token, SECRET) as { two_factor_elevated: unknown }).two_factor_elevated).toBe(false);
    });
  });

  describe('restSessionUser', () => {
    it('preserves the fields callers carry alongside the session user', () => {
      const user = restSessionUser(appSession(true, { is_tenant_admin: true }));

      expect(user).toMatchObject({ is_tenant_admin: true, two_factor_elevated: true });
    });

    it('does not mutate the session it reads', () => {
      const session = appSession(true);
      restSessionUser(session);

      expect(session.user).not.toHaveProperty('two_factor_elevated');
    });
  });

  describe('resolveSessionPrincipalId', () => {
    it('reads and trims user_id', () => {
      expect(resolveSessionPrincipalId({ user_id: '  user-1  ' })).toBe('user-1');
    });

    it('returns undefined for a blank or missing principal', () => {
      expect(resolveSessionPrincipalId({ user_id: '   ' })).toBeUndefined();
      expect(resolveSessionPrincipalId({})).toBeUndefined();
      expect(resolveSessionPrincipalId(null)).toBeUndefined();
      expect(resolveSessionPrincipalId(undefined)).toBeUndefined();
    });

    it('never falls back to a legacy user.id', () => {
      expect(resolveSessionPrincipalId({ id: 'legacy-1' } as never)).toBeUndefined();
    });
  });

  describe('getRestApiBaseUrl', () => {
    it('prefers the runtime REST_API_BASE_URL', () => {
      process.env.NEXT_PUBLIC_REST_API_BASE_URL = 'http://localhost:8000/v1';
      process.env.REST_API_BASE_URL = 'http://rest:8000/v1/';

      expect(getRestApiBaseUrl()).toBe('http://rest:8000/v1');
    });

    it('falls back to the build-time NEXT_PUBLIC_REST_API_BASE_URL', () => {
      process.env.NEXT_PUBLIC_REST_API_BASE_URL = 'http://localhost:9000/v1/';

      expect(getRestApiBaseUrl()).toBe('http://localhost:9000/v1');
    });

    it('defaults to the local REST port when neither is set', () => {
      expect(getRestApiBaseUrl()).toBe('http://localhost:8000/v1');
    });

    it('keeps the frozen build-time constant for existing call sites', () => {
      expect(typeof REST_API_BASE_URL).toBe('string');
      expect(REST_API_BASE_URL.length).toBeGreaterThan(0);
    });
  });
});

describe('isSessionElevated (decision D8)', () => {
  it('is true only for the boolean true', () => {
    expect(isSessionElevated({ twoFactorElevated: true })).toBe(true);
    expect(isSessionElevated({ twoFactorElevated: false })).toBe(false);
    expect(isSessionElevated({ twoFactorElevated: 'true' })).toBe(false);
    expect(isSessionElevated({})).toBe(false);
    expect(isSessionElevated(null)).toBe(false);
    expect(isSessionElevated(undefined)).toBe(false);
  });
});
