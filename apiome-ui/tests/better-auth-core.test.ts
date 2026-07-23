/**
 * Wiring tests for the Better Auth core install (OLO-10.2): `lib/auth/auth.ts` (server instance +
 * request handler) and `lib/auth/auth-client.ts` (browser client).
 *
 * `better-auth` ships ESM-only, which ts-jest's CommonJS transform cannot `require`, so the package
 * (and the Postgres pool) are mocked. That is sufficient here: the goal is to prove *our* modules
 * pass the intended configuration to Better Auth — the shared pool, `NEXTAUTH_SECRET`, the
 * `/api/auth` base path, and the `nextCookies` plugin — not to exercise Better Auth itself.
 */

const mockHandler = jest.fn();
const mockBetterAuth = jest.fn(() => ({ handler: mockHandler }));
const mockNextCookies = jest.fn(() => ({ id: 'next-cookies' }));
const mockCreateAuthClient = jest.fn(() => ({
  signIn: jest.fn(),
  signOut: jest.fn(),
  useSession: jest.fn(),
  getSession: jest.fn(),
}));

jest.mock('better-auth', () => ({ betterAuth: mockBetterAuth }));
jest.mock('better-auth/next-js', () => ({ nextCookies: mockNextCookies }));
jest.mock('better-auth/react', () => ({ createAuthClient: mockCreateAuthClient }));
// `better-auth/api` is ESM-only (ts-jest's CommonJS transform cannot require it). The credential
// wiring (`better-auth-credentials.ts`, transitively imported by auth.ts) calls createAuthMiddleware
// at module load, so stub it to return the handler unchanged and provide a minimal APIError.
jest.mock('better-auth/api', () => ({
  createAuthMiddleware: (handler: unknown) => handler,
  APIError: class APIError extends Error {
    status: string;
    body: unknown;
    constructor(status: string, body?: { message?: string }) {
      super(body?.message);
      this.status = status;
      this.body = body;
    }
  },
}));
// Stub the shared Postgres pool so importing the server instance never opens a real connection.
jest.mock('@lib/db/db', () => ({ query: jest.fn() }));

describe('lib/auth/auth.ts (Better Auth server instance)', () => {
  const originalSecret = process.env.NEXTAUTH_SECRET;
  const originalBetterAuthUrl = process.env.BETTER_AUTH_URL;
  const originalNextAuthUrl = process.env.NEXTAUTH_URL;
  const originalNodeEnv = process.env.NODE_ENV;
  const originalCookieDomain = process.env.NEXTAUTH_COOKIE_DOMAIN;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.resetModules();
  });

  afterEach(() => {
    restoreEnv('NEXTAUTH_SECRET', originalSecret);
    restoreEnv('BETTER_AUTH_URL', originalBetterAuthUrl);
    restoreEnv('NEXTAUTH_URL', originalNextAuthUrl);
    restoreEnv('NODE_ENV', originalNodeEnv);
    restoreEnv('NEXTAUTH_COOKIE_DOMAIN', originalCookieDomain);
  });

  function restoreEnv(key: string, value: string | undefined): void {
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  it('constructs Better Auth with the shared pool, NEXTAUTH_SECRET and /api/auth base path', async () => {
    process.env.NEXTAUTH_SECRET = 'test-secret';
    process.env.BETTER_AUTH_URL = 'https://app.example.test';

    const { auth } = await import('@lib/auth/auth');

    expect(mockBetterAuth).toHaveBeenCalledTimes(1);
    const config = mockBetterAuth.mock.calls[0][0];
    expect(config.appName).toBe('apiome');
    expect(config.secret).toBe('test-secret');
    expect(config.baseURL).toBe('https://app.example.test');
    expect(config.basePath).toBe('/api/auth');
    expect(config.database).toBeDefined();
    // nextCookies must be registered (as the sole baseline plugin) so server actions can set cookies.
    expect(mockNextCookies).toHaveBeenCalledTimes(1);
    expect(config.plugins).toHaveLength(1);
    expect(auth).toBeDefined();
  });

  it('passes the OLO-10.3 session strategy, cookie parity and trusted origins', async () => {
    process.env.NEXTAUTH_SECRET = 'test-secret';
    process.env.NODE_ENV = 'production';
    process.env.NEXTAUTH_URL = 'https://main.apiome.dev';
    process.env.NEXTAUTH_COOKIE_DOMAIN = '.apiome.dev';

    await import('@lib/auth/auth');

    const config = mockBetterAuth.mock.calls[0][0];
    // 30-day DB session with 24h refresh + a short signed cookie cache (design §1).
    expect(config.session).toEqual({
      expiresIn: 60 * 60 * 24 * 30,
      updateAge: 60 * 60 * 24,
      cookieCache: { enabled: true, maxAge: 60 },
    });
    // Cross-subdomain cookie scoping on the shared parent domain, matching the legacy engine.
    expect(config.advanced).toEqual({
      crossSubDomainCookies: { enabled: true, domain: '.apiome.dev' },
    });
    expect(config.trustedOrigins).toContain('https://*.apiome.dev');
  });

  it('keeps apiome.users as the user model via field mapping (design §2.1)', async () => {
    process.env.NEXTAUTH_SECRET = 'test-secret';

    await import('@lib/auth/auth');

    const config = mockBetterAuth.mock.calls[0][0];
    expect(config.user).toEqual({
      modelName: 'users',
      fields: {
        emailVerified: 'verified',
        createdAt: 'created_at',
        updatedAt: 'updated_at',
      },
    });
  });

  it('enables credential sign-in with bcrypt hashing/verification (OLO-10.5)', async () => {
    process.env.NEXTAUTH_SECRET = 'test-secret';

    await import('@lib/auth/auth');

    const config = mockBetterAuth.mock.calls[0][0];
    expect(config.emailAndPassword.enabled).toBe(true);
    // Self-service sign-up stays off (new users flow through apiome's own path), email verification on.
    expect(config.emailAndPassword.disableSignUp).toBe(true);
    expect(config.emailAndPassword.requireEmailVerification).toBe(true);
    // Custom bcrypt hash/verify replaces Better Auth's default scrypt so relocated hashes validate.
    expect(typeof config.emailAndPassword.password.hash).toBe('function');
    expect(typeof config.emailAndPassword.password.verify).toBe('function');
  });

  it('wires the per-account/per-IP credential rate-limit hooks (OLO-10.5)', async () => {
    process.env.NEXTAUTH_SECRET = 'test-secret';

    await import('@lib/auth/auth');

    const config = mockBetterAuth.mock.calls[0][0];
    expect(typeof config.hooks.before).toBe('function');
    expect(typeof config.hooks.after).toBe('function');
  });

  it('falls back to NEXTAUTH_URL for the base URL when BETTER_AUTH_URL is unset', async () => {
    process.env.NEXTAUTH_SECRET = 'test-secret';
    delete process.env.BETTER_AUTH_URL;
    process.env.NEXTAUTH_URL = 'https://legacy.example.test';

    await import('@lib/auth/auth');

    expect(mockBetterAuth.mock.calls[0][0].baseURL).toBe('https://legacy.example.test');
  });

  it('betterAuthHandler delegates the request to auth.handler', async () => {
    mockHandler.mockResolvedValue('handled');
    const { betterAuthHandler } = await import('@lib/auth/auth');
    const request = { url: 'https://app.example.test/api/auth/get-session' } as unknown as Request;

    const result = await betterAuthHandler(request);

    expect(mockHandler).toHaveBeenCalledWith(request);
    expect(result).toBe('handled');
  });
});

describe('lib/auth/auth-client.ts (Better Auth browser client)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.resetModules();
  });

  it('creates the client on the /api/auth base path', async () => {
    const { authClient } = await import('@lib/auth/auth-client');

    expect(mockCreateAuthClient).toHaveBeenCalledWith({ basePath: '/api/auth' });
    expect(authClient).toBeDefined();
    expect(authClient.signIn).toBeDefined();
  });
});
