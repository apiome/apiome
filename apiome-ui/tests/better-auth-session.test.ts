import {
  SESSION_COOKIE_CACHE_MAX_AGE_SECONDS,
  SESSION_EXPIRES_IN_SECONDS,
  SESSION_UPDATE_AGE_SECONDS,
  buildBetterAuthAdvancedOptions,
  buildBetterAuthCrossSubDomainCookies,
  buildBetterAuthSessionOptions,
  buildBetterAuthTrustedOrigins,
  resolveBetterAuthSecret,
} from '@lib/auth/better-auth-session';

/**
 * Tests for the Better Auth session strategy & cookie parity builders (OLO-10.3).
 *
 * These assert the concrete decisions from the migration design (§1): the session lifetime/refresh
 * match NextAuth v4 so nobody is logged out at cutover; the cookie is scoped to the same shared parent
 * domain as today so sessions persist across the app's subdomains; and the secret is reused from
 * NextAuth but overridable/rotatable. The builders are pure functions of the environment, so the
 * tests drive them purely by mutating `process.env`.
 */
describe('better-auth-session builders (OLO-10.3)', () => {
  const env = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...env };
  });

  afterAll(() => {
    process.env = env;
  });

  describe('session lifetime constants match NextAuth v4 defaults', () => {
    it('uses a 30-day expiry and 24h refresh so no user is logged out at cutover', () => {
      expect(SESSION_EXPIRES_IN_SECONDS).toBe(60 * 60 * 24 * 30);
      expect(SESSION_UPDATE_AGE_SECONDS).toBe(60 * 60 * 24);
    });

    it('caps the cookie cache at a short 60-second TTL', () => {
      expect(SESSION_COOKIE_CACHE_MAX_AGE_SECONDS).toBe(60);
    });
  });

  describe('buildBetterAuthSessionOptions', () => {
    it('emits the TTL, refresh cadence and an enabled short-lived cookie cache', () => {
      expect(buildBetterAuthSessionOptions()).toEqual({
        expiresIn: SESSION_EXPIRES_IN_SECONDS,
        updateAge: SESSION_UPDATE_AGE_SECONDS,
        cookieCache: {
          enabled: true,
          maxAge: SESSION_COOKIE_CACHE_MAX_AGE_SECONDS,
        },
      });
    });
  });

  describe('resolveBetterAuthSecret', () => {
    it('reuses NEXTAUTH_SECRET when no dedicated secret is set', () => {
      delete process.env.BETTER_AUTH_SECRET;
      process.env.NEXTAUTH_SECRET = 'legacy-secret';
      expect(resolveBetterAuthSecret()).toBe('legacy-secret');
    });

    it('lets BETTER_AUTH_SECRET take over for the rotation path', () => {
      process.env.NEXTAUTH_SECRET = 'legacy-secret';
      process.env.BETTER_AUTH_SECRET = 'rotated-secret';
      expect(resolveBetterAuthSecret()).toBe('rotated-secret');
    });

    it('falls back to NEXTAUTH_SECRET when BETTER_AUTH_SECRET is blank', () => {
      process.env.NEXTAUTH_SECRET = 'legacy-secret';
      process.env.BETTER_AUTH_SECRET = '   ';
      expect(resolveBetterAuthSecret()).toBe('legacy-secret');
    });

    it('returns undefined when neither secret is configured', () => {
      delete process.env.BETTER_AUTH_SECRET;
      delete process.env.NEXTAUTH_SECRET;
      expect(resolveBetterAuthSecret()).toBeUndefined();
    });
  });

  describe('buildBetterAuthCrossSubDomainCookies', () => {
    it('scopes cookies to the configured shared parent domain in production', () => {
      process.env.NODE_ENV = 'production';
      process.env.NEXTAUTH_COOKIE_DOMAIN = '.apiome.dev';
      process.env.NEXTAUTH_URL = 'https://main.apiome.dev';

      expect(buildBetterAuthCrossSubDomainCookies()).toEqual({
        enabled: true,
        domain: '.apiome.dev',
      });
    });

    it('infers the shared parent domain from NEXTAUTH_URL when unset', () => {
      process.env.NODE_ENV = 'production';
      delete process.env.NEXTAUTH_COOKIE_DOMAIN;
      process.env.NEXTAUTH_URL = 'https://main.apiome.dev';

      expect(buildBetterAuthCrossSubDomainCookies()).toEqual({
        enabled: true,
        domain: '.apiome.dev',
      });
    });

    it('leaves cookies host-only outside production (dev/localhost)', () => {
      process.env.NODE_ENV = 'development';
      process.env.NEXTAUTH_COOKIE_DOMAIN = '.apiome.dev';
      process.env.NEXTAUTH_URL = 'http://localhost:3000';

      expect(buildBetterAuthCrossSubDomainCookies()).toBeUndefined();
    });
  });

  describe('buildBetterAuthAdvancedOptions', () => {
    it('carries crossSubDomainCookies when a shared domain applies', () => {
      process.env.NODE_ENV = 'production';
      process.env.NEXTAUTH_COOKIE_DOMAIN = '.apiome.dev';
      process.env.NEXTAUTH_URL = 'https://main.apiome.dev';

      expect(buildBetterAuthAdvancedOptions()).toEqual({
        crossSubDomainCookies: { enabled: true, domain: '.apiome.dev' },
      });
    });

    it('is empty (host-only defaults) in dev', () => {
      process.env.NODE_ENV = 'development';
      process.env.NEXTAUTH_URL = 'http://localhost:3000';

      expect(buildBetterAuthAdvancedOptions()).toEqual({});
    });
  });

  describe('buildBetterAuthTrustedOrigins', () => {
    it('trusts the app origins plus a wildcard for the shared cookie domain in production', () => {
      process.env.NODE_ENV = 'production';
      process.env.NEXTAUTH_COOKIE_DOMAIN = '.apiome.dev';
      process.env.NEXTAUTH_URL = 'https://main.apiome.dev';
      process.env.NEXT_PUBLIC_STUDIO_URL = 'https://suite.apiome.dev';

      const origins = buildBetterAuthTrustedOrigins();

      expect(origins).toContain('https://main.apiome.dev');
      expect(origins).toContain('https://suite.apiome.dev');
      // The wildcard lets a login return to any sibling subdomain covered by the shared cookie.
      expect(origins).toContain('https://*.apiome.dev');
    });

    it('trusts only the explicit app origins in dev (no wildcard)', () => {
      process.env.NODE_ENV = 'development';
      process.env.NEXTAUTH_URL = 'http://localhost:3000';
      delete process.env.NEXTAUTH_COOKIE_DOMAIN;
      delete process.env.NEXT_PUBLIC_STUDIO_URL;

      const origins = buildBetterAuthTrustedOrigins();

      expect(origins).toContain('http://localhost:3000');
      expect(origins.some((o) => o.includes('*'))).toBe(false);
    });

    it('de-duplicates origins', () => {
      process.env.NODE_ENV = 'production';
      process.env.NEXTAUTH_URL = 'https://main.apiome.dev';
      process.env.NEXT_PUBLIC_MAIN_APP_URL = 'https://main.apiome.dev';

      const origins = buildBetterAuthTrustedOrigins();

      expect(origins.filter((o) => o === 'https://main.apiome.dev')).toHaveLength(1);
    });
  });
});
