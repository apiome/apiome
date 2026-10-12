/**
 * @jest-environment node
 *
 * The second factor after an OAuth sign-in (TFA-1.1, #5655).
 *
 * Better Auth 1.6.25 challenges password sign-ins only, so `oauthTwoFactorChallengeHandler`
 * recreates the plugin's challenge for the provider callback. Two things are pinned here:
 *
 * 1. **What the handler does** — driven with a faked Better Auth hook context: who is challenged,
 *    what is written, where the browser is sent, and when a trusted device is let through.
 * 2. **What it depends on** — the installed plugin's cookie names, record identifiers and trust
 *    signature are read from `node_modules` and compared with this module's, so a Better Auth
 *    upgrade that changes one fails here instead of silently dropping the challenge.
 */

import { createHmac } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockDeleteSessionCookie = jest.fn();
const mockExpireCookie = jest.fn();
let randomCounter = 0;

jest.mock('better-auth/cookies', () => ({
  deleteSessionCookie: (...args: unknown[]) => mockDeleteSessionCookie(...args),
  expireCookie: (...args: unknown[]) => mockExpireCookie(...args),
}));
jest.mock('better-auth/crypto', () => ({
  generateRandomString: (length: number) => `rand${++randomCounter}`.padEnd(length, '0'),
}));
// `better-auth/api` is ESM-only; the callback-path helper this module reuses lives in a file that
// imports it. Nothing under test calls into it.
jest.mock('better-auth/api', () => ({
  createAuthMiddleware: (handler: unknown) => handler,
  APIError: class APIError extends Error {},
}));
jest.mock('@lib/auth/send-two-factor-email-otp', () => ({
  isTwoFactorEmailOtpConfigured: jest.fn(() => false),
}));

import { isTwoFactorEmailOtpConfigured } from '@lib/auth/send-two-factor-email-otp';
import {
  TRUST_DEVICE_COOKIE_NAME,
  TWO_FACTOR_CHALLENGE_MAX_AGE_SECONDS,
  TWO_FACTOR_COOKIE_NAME,
  oauthTwoFactorChallengeHandler,
  signTrustedDevice,
} from '@lib/auth/two-factor-oauth-challenge';
import { TRUST_DEVICE_MAX_AGE_SECONDS } from '@lib/auth/two-factor-policy';

const mockEmailOtp = isTwoFactorEmailOtpConfigured as unknown as jest.Mock;

const SECRET = 'test-auth-secret';
const USER_ID = '660e8400-e29b-41d4-a716-446655440001';
const SESSION_TOKEN = 'session-token-1';
const NOW = Date.parse('2026-10-11T12:00:00Z');

/** A redirect the fake `ctx.redirect` builds, so a thrown one can be recognised. */
class FakeRedirect {
  constructor(public readonly url: string) {}
}

interface World {
  path?: string;
  /** `null` = the callback issued no session. */
  twoFactorEnabled?: boolean | null;
  /** Signed cookies the browser sent, by cookie name. */
  cookies?: Record<string, string>;
  /** Verification records that exist, by identifier. */
  verifications?: Record<string, { value: string; expiresAt: Date }>;
  /** The user's `twoFactor` row, or `null` when there is none. */
  enrolment?: { verified?: boolean | null } | null;
  /** Where the callback was redirecting. */
  location?: string | null;
  noSession?: boolean;
}

/** Build a faked hook context and the recorders the assertions read. */
function makeContext(world: World = {}) {
  const verifications = new Map(Object.entries(world.verifications ?? {}));
  const created: { value: string; identifier: string; expiresAt: Date }[] = [];
  const deletedVerifications: string[] = [];
  const deletedSessions: string[] = [];
  const signedCookies: { name: string; value: string; attributes?: Record<string, unknown> }[] = [];
  const setNewSession = jest.fn();

  const ctx = {
    path: world.path ?? '/oauth2/callback/github',
    context: {
      secret: SECRET,
      newSession: world.noSession
        ? null
        : {
            user: {
              id: USER_ID,
              twoFactorEnabled: 'twoFactorEnabled' in world ? world.twoFactorEnabled : true,
            },
            session: { token: SESSION_TOKEN },
          },
      setNewSession,
      returned:
        world.location === null
          ? undefined
          : { headers: new Headers({ location: world.location ?? '/ade/dashboard' }) },
      responseHeaders: new Headers(),
      createAuthCookie: (name: string, attributes?: { maxAge?: number }) => ({
        name: `better-auth.${name}`,
        attributes: { httpOnly: true, ...attributes },
      }),
      internalAdapter: {
        deleteSession: async (token: string) => void deletedSessions.push(token),
        createVerificationValue: async (data: { value: string; identifier: string; expiresAt: Date }) => {
          created.push(data);
          verifications.set(data.identifier, data);
        },
        findVerificationValue: async (identifier: string) => verifications.get(identifier) ?? null,
        deleteVerificationByIdentifier: async (identifier: string) => {
          deletedVerifications.push(identifier);
          verifications.delete(identifier);
        },
      },
      adapter: {
        findOne: jest.fn(async () => (world.enrolment === undefined ? { verified: true } : world.enrolment)),
      },
    },
    getSignedCookie: async (name: string) => world.cookies?.[name] ?? null,
    setSignedCookie: async (name: string, value: string, _secret: string, attributes?: Record<string, unknown>) =>
      void signedCookies.push({ name, value, attributes }),
    redirect: (url: string) => new FakeRedirect(url),
  };
  return { ctx, created, deletedVerifications, deletedSessions, signedCookies, setNewSession };
}

/** Run the handler and return the redirect it threw, or `null` when it returned normally. */
async function run(ctx: unknown): Promise<URL | null> {
  try {
    await oauthTwoFactorChallengeHandler(ctx);
    return null;
  } catch (thrown) {
    if (thrown instanceof FakeRedirect) return new URL(thrown.url, 'https://app.test');
    throw thrown;
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  randomCounter = 0;
  mockEmailOtp.mockReturnValue(false);
  jest.useFakeTimers({ now: NOW });
});

afterEach(() => {
  jest.useRealTimers();
});

describe('who is challenged', () => {
  test.each([
    ['a password sign-in', '/sign-in/email'],
    ['a session read', '/get-session'],
    ['a second-factor verification', '/two-factor/verify-totp'],
    ['no path at all', undefined],
  ])('leaves %s alone', async (_name, requestPath) => {
    const world = makeContext();
    world.ctx.path = requestPath as string;
    expect(await run(world.ctx)).toBeNull();
    expect(world.deletedSessions).toEqual([]);
    expect(world.created).toEqual([]);
  });

  test('leaves a callback that issued no session alone (error redirect, link branch)', async () => {
    const world = makeContext({ noSession: true });
    expect(await run(world.ctx)).toBeNull();
    expect(mockDeleteSessionCookie).not.toHaveBeenCalled();
  });

  test.each([false, null])('lets a user without two-factor straight in (twoFactorEnabled=%p)', async (flag) => {
    const world = makeContext({ twoFactorEnabled: flag });
    expect(await run(world.ctx)).toBeNull();
    expect(world.deletedSessions).toEqual([]);
    expect(world.signedCookies).toEqual([]);
    expect(mockDeleteSessionCookie).not.toHaveBeenCalled();
  });

  test.each(['github', 'gitlab', 'azure', 'google'])('challenges an enrolled user signing in with %s', async (provider) => {
    const world = makeContext({ path: `/oauth2/callback/${provider}` });
    const redirect = await run(world.ctx);
    expect(redirect?.pathname).toBe('/login/2fa');
    expect(world.deletedSessions).toEqual([SESSION_TOKEN]);
  });
});

describe('starting the challenge', () => {
  test('takes back the session the callback issued', async () => {
    const world = makeContext();
    await run(world.ctx);

    expect(mockDeleteSessionCookie).toHaveBeenCalledWith(world.ctx, true);
    expect(world.deletedSessions).toEqual([SESSION_TOKEN]);
    // Hooks that run later must not see a session that no longer exists.
    expect(world.setNewSession).toHaveBeenCalledWith(null);
  });

  test("writes the plugin's challenge: the user record, its attempt counter and the signed cookie", async () => {
    const world = makeContext();
    await run(world.ctx);

    const expiresAt = new Date(NOW + TWO_FACTOR_CHALLENGE_MAX_AGE_SECONDS * 1000);
    const identifier = world.created[0].identifier;
    expect(identifier).toMatch(/^2fa-.{20}$/);
    expect(world.created).toEqual([
      { value: USER_ID, identifier, expiresAt },
      { value: '0', identifier: `2fa-attempts-${identifier}`, expiresAt },
    ]);
    expect(world.signedCookies).toEqual([
      {
        name: `better-auth.${TWO_FACTOR_COOKIE_NAME}`,
        value: identifier,
        attributes: { httpOnly: true, maxAge: TWO_FACTOR_CHALLENGE_MAX_AGE_SECONDS },
      },
    ]);
  });

  test('sends the browser to the second step, carrying where it was going', async () => {
    const world = makeContext({ location: '/ade/dashboard/projects?tab=all' });
    const redirect = await run(world.ctx);

    expect(redirect?.pathname).toBe('/login/2fa');
    expect(redirect?.searchParams.get('callbackUrl')).toBe('/ade/dashboard/projects?tab=all');
    expect(redirect?.searchParams.get('methods')).toBe('totp');
  });

  test('reads the destination from the response headers when the returned value has none', async () => {
    const world = makeContext({ location: null });
    world.ctx.context.responseHeaders.set('location', 'https://app.test/ade');
    expect((await run(world.ctx))?.searchParams.get('callbackUrl')).toBe('https://app.test/ade');
  });

  test('omits the destination when the callback named none', async () => {
    const world = makeContext({ location: null });
    expect((await run(world.ctx))?.searchParams.has('callbackUrl')).toBe(false);
  });

  test.each<[string, World, boolean, string | null]>([
    ['authenticator only', {}, false, 'totp'],
    ['authenticator and email', {}, true, 'totp,otp'],
    ['email only — no authenticator row', { enrolment: null }, true, 'otp'],
    ['email only — unverified authenticator', { enrolment: { verified: false } }, true, 'otp'],
    ['none named', { enrolment: null }, false, null],
  ])('offers the methods the user can use: %s', async (_name, world, emailOtp, expected) => {
    mockEmailOtp.mockReturnValue(emailOtp);
    const redirect = await run(makeContext(world).ctx);
    expect(redirect?.searchParams.get('methods')).toBe(expected);
  });
});

describe('trusted device', () => {
  const TRUST_ID = 'trust-device-existing';
  const cookieName = `better-auth.${TRUST_DEVICE_COOKIE_NAME}`;
  const trustCookie = (userId = USER_ID, identifier = TRUST_ID) =>
    `${signTrustedDevice(SECRET, userId, identifier)}!${identifier}`;
  const liveRecord = (value = USER_ID, expiresAt = new Date(NOW + 60_000)) => ({
    [TRUST_ID]: { value, expiresAt },
  });

  test('skips the second step and rotates the trust record', async () => {
    const world = makeContext({ cookies: { [cookieName]: trustCookie() }, verifications: liveRecord() });
    expect(await run(world.ctx)).toBeNull();

    // The session stands.
    expect(world.deletedSessions).toEqual([]);
    expect(mockDeleteSessionCookie).not.toHaveBeenCalled();
    // The old record is spent and a new one issued for the full window, as the plugin does.
    expect(world.deletedVerifications).toEqual([TRUST_ID]);
    const [next] = world.created;
    expect(next.identifier).toMatch(/^trust-device-.{32}$/);
    expect(next).toMatchObject({
      value: USER_ID,
      expiresAt: new Date(NOW + TRUST_DEVICE_MAX_AGE_SECONDS * 1000),
    });
    expect(world.signedCookies).toEqual([
      {
        name: cookieName,
        value: `${signTrustedDevice(SECRET, USER_ID, next.identifier)}!${next.identifier}`,
        attributes: { httpOnly: true, maxAge: TRUST_DEVICE_MAX_AGE_SECONDS },
      },
    ]);
  });

  test.each<[string, string, Record<string, { value: string; expiresAt: Date }>]>([
    ['a forged signature', `forged!${TRUST_ID}`, liveRecord()],
    ['a cookie signed for another user', trustCookie('someone-else'), liveRecord()],
    ['a record that belongs to another user', trustCookie(), liveRecord('someone-else')],
    ['an expired record', trustCookie(), liveRecord(USER_ID, new Date(NOW - 1))],
    ['a revoked record', trustCookie(), {}],
    ['a malformed cookie', 'no-separator', liveRecord()],
  ])('challenges, and expires the cookie, for %s', async (_name, cookie, verifications) => {
    const world = makeContext({ cookies: { [cookieName]: cookie }, verifications });
    const redirect = await run(world.ctx);

    expect(redirect?.pathname).toBe('/login/2fa');
    expect(world.deletedSessions).toEqual([SESSION_TOKEN]);
    expect(mockExpireCookie).toHaveBeenCalledWith(world.ctx, expect.objectContaining({ name: cookieName }));
    // The trust record is neither consumed nor reissued.
    expect(world.deletedVerifications).toEqual([]);
    expect(world.created.some((record) => record.identifier.startsWith('trust-device-'))).toBe(false);
  });

  test('challenges without touching cookies when the browser sent no trust cookie', async () => {
    const world = makeContext();
    expect((await run(world.ctx))?.pathname).toBe('/login/2fa');
    expect(mockExpireCookie).not.toHaveBeenCalled();
  });
});

describe('the Better Auth internals this module mirrors (re-check on upgrade)', () => {
  const PLUGIN = path.resolve(
    __dirname,
    '..',
    '..',
    'node_modules',
    'better-auth',
    'dist',
    'plugins',
    'two-factor'
  );
  const read = (file: string) => fs.readFileSync(path.join(PLUGIN, file), 'utf8');
  const constants = read('constant.mjs');
  const pluginIndex = read('index.mjs');
  const verify = read('verify-two-factor.mjs');

  test('cookie names match the plugin', () => {
    expect(constants).toContain(`TWO_FACTOR_COOKIE_NAME = "${TWO_FACTOR_COOKIE_NAME}"`);
    expect(constants).toContain(`TRUST_DEVICE_COOKIE_NAME = "${TRUST_DEVICE_COOKIE_NAME}"`);
  });

  test('the challenge lifetime matches the plugin default', () => {
    expect(pluginIndex).toContain(`twoFactorCookieMaxAge ?? ${TWO_FACTOR_CHALLENGE_MAX_AGE_SECONDS}`);
  });

  test('the plugin creates, and its verifier reads, the records this module writes', () => {
    // Created by the plugin's own password-sign-in hook…
    expect(pluginIndex).toContain('const identifier = `2fa-${generateRandomString(20)}`');
    expect(pluginIndex).toContain('identifier: `2fa-attempts-${identifier}`');
    expect(pluginIndex).toContain('value: data.user.id');
    // …and looked up by the verify endpoints from the signed cookie.
    expect(verify).toContain('findVerificationValue(signedTwoFactorCookie)');
    expect(verify).toContain('const identifier = `2fa-attempts-${signedTwoFactorCookie}`');
    expect(verify).toContain('findUserById(verificationToken.value)');
  });

  test('the trusted-device signature matches the plugin', () => {
    expect(pluginIndex).toContain(
      'createHMAC("SHA-256", "base64urlnopad").sign(ctx.context.secret, `${data.user.id}!${trustIdentifier}`)'
    );
    expect(pluginIndex).toContain('trustDeviceCookie.split("!")');
    expect(pluginIndex).toContain('`trust-device-${generateRandomString(32)}`');

    // SHA-256 HMAC, base64url without padding — computed here the long way round.
    const expected = createHmac('sha256', SECRET)
      .update(`${USER_ID}!trust-device-abc`)
      .digest('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
    expect(signTrustedDevice(SECRET, USER_ID, 'trust-device-abc')).toBe(expected);
  });

  test('the plugin still does not challenge OAuth callbacks itself', () => {
    // If a Better Auth release adds the callback to its own matcher, both would challenge the
    // same sign-in: remove `two-factor-oauth-challenge.ts` rather than keep it beside the plugin.
    const matcher = pluginIndex.match(/matcher\(context\) \{\s*return ([^;]+);/)?.[1] ?? '';
    expect(matcher).toContain('"/sign-in/email"');
    expect(matcher).not.toMatch(/callback|oauth/i);
  });
});
