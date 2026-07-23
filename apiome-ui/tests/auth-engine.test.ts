import {
  AUTH_ENGINE_BETTER_AUTH,
  AUTH_ENGINE_NEXT_AUTH,
  getAuthEngine,
  isBetterAuthEngine,
} from '@lib/auth/auth-engine';

/**
 * Tests for the Better Auth migration engine flag (OLO-10.2). The flag must fail safe: only the
 * exact literal `better-auth` selects Better Auth, so a typo or blank value can never leave auth
 * being served by a half-configured engine.
 */
describe('auth-engine flag', () => {
  const originalEngine = process.env.AUTH_ENGINE;

  afterEach(() => {
    if (originalEngine === undefined) {
      delete process.env.AUTH_ENGINE;
    } else {
      process.env.AUTH_ENGINE = originalEngine;
    }
  });

  it('defaults to next-auth when AUTH_ENGINE is unset', () => {
    delete process.env.AUTH_ENGINE;
    expect(getAuthEngine()).toBe(AUTH_ENGINE_NEXT_AUTH);
    expect(isBetterAuthEngine()).toBe(false);
  });

  it('selects better-auth for the exact literal value', () => {
    process.env.AUTH_ENGINE = 'better-auth';
    expect(getAuthEngine()).toBe(AUTH_ENGINE_BETTER_AUTH);
    expect(isBetterAuthEngine()).toBe(true);
  });

  it('tolerates surrounding whitespace on the better-auth value', () => {
    process.env.AUTH_ENGINE = '  better-auth  ';
    expect(getAuthEngine()).toBe(AUTH_ENGINE_BETTER_AUTH);
    expect(isBetterAuthEngine()).toBe(true);
  });

  it('falls back to next-auth for a blank value', () => {
    process.env.AUTH_ENGINE = '   ';
    expect(getAuthEngine()).toBe(AUTH_ENGINE_NEXT_AUTH);
    expect(isBetterAuthEngine()).toBe(false);
  });

  it.each(['NextAuth', 'better_auth', 'betterauth', 'BETTER-AUTH', 'nextauth', 'unknown'])(
    'falls back to next-auth for the non-matching value %p',
    (value) => {
      process.env.AUTH_ENGINE = value;
      expect(getAuthEngine()).toBe(AUTH_ENGINE_NEXT_AUTH);
      expect(isBetterAuthEngine()).toBe(false);
    }
  );

  it('exposes the two engine constants as the expected literals', () => {
    expect(AUTH_ENGINE_NEXT_AUTH).toBe('next-auth');
    expect(AUTH_ENGINE_BETTER_AUTH).toBe('better-auth');
  });
});
