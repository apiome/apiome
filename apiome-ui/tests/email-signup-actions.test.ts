/**
 * Email sign-up server actions (SGN-1.1, #5650): the policy gate, no enumeration, canonicalization,
 * the no-sender path, per-address budgets, resend and link redemption — and the SGN-1.5 (#5654)
 * abuse guards: the disposable-email blocklist, the optional Turnstile CAPTCHA, and the
 * `auth_events` row each refusal leaves.
 */

const mockFindSignupAccount = jest.fn();
const mockIssueVerificationToken = jest.fn();
const mockRedeemVerificationToken = jest.fn();
const mockFindPendingSignup = jest.fn();
const mockCreateUser = jest.fn();
const mockInsertAuthOneTimeCode = jest.fn();
const mockSendSignupEmail = jest.fn();
const mockResolveSignupPolicy = jest.fn();
const mockRecordSignupGuardEvent = jest.fn();
const mockVerifyTurnstileToken = jest.fn();

jest.mock('next/headers', () => ({
  headers: async () => new Headers({ 'x-forwarded-for': '203.0.113.7' }),
}));
jest.mock('../lib/db/email-verification', () => ({
  findSignupAccount: (...args: unknown[]) => mockFindSignupAccount(...args),
  issueVerificationToken: (...args: unknown[]) => mockIssueVerificationToken(...args),
  redeemVerificationToken: (...args: unknown[]) => mockRedeemVerificationToken(...args),
  findPendingSignup: (...args: unknown[]) => mockFindPendingSignup(...args),
}));
jest.mock('../lib/db/admin-helper', () => ({
  createUser: (...args: unknown[]) => mockCreateUser(...args),
}));
jest.mock('../lib/db/oauth-signup', () => ({
  insertAuthOneTimeCode: (...args: unknown[]) => mockInsertAuthOneTimeCode(...args),
}));
jest.mock('../lib/auth/send-signup-email', () => ({
  sendSignupEmail: (...args: unknown[]) => mockSendSignupEmail(...args),
}));
jest.mock('../lib/auth/signup-policy-resolver', () => ({
  resolveSignupPolicy: (...args: unknown[]) => mockResolveSignupPolicy(...args),
}));
jest.mock('../lib/auth/signup-guard-events', () => ({
  ...jest.requireActual('../lib/auth/signup-guard-events'),
  recordSignupGuardEvent: (...args: unknown[]) => mockRecordSignupGuardEvent(...args),
}));
jest.mock('../lib/auth/turnstile', () => ({
  ...jest.requireActual('../lib/auth/turnstile'),
  verifyTurnstileToken: (...args: unknown[]) => mockVerifyTurnstileToken(...args),
}));

import bcrypt from 'bcrypt';
import {
  resendSignupVerification,
  startEmailSignup,
  verifyEmailSignup,
} from '../lib/auth/email-signup-actions';
import { _resetLoginRateLimit } from '../lib/auth/login-rate-limit';

const ENV_KEYS = [
  'SENDGRID_API_KEY',
  'EMAIL_FROM',
  'BETTER_AUTH_URL',
  'TURNSTILE_SITE_KEY',
  'TURNSTILE_SECRET_KEY',
] as const;
const saved: Record<string, string | undefined> = {};

const OPEN = { mode: 'open', allowedEmailDomains: [], source: 'db' };
const GOOD = { name: 'Ada Lovelace', email: '  Ada@Example.COM ', password: 'Analytical1' };
const NEW_ACCOUNT = { id: 'u-1', name: 'Ada Lovelace', email: 'ada@example.com', verified: false, enabled: true };

beforeAll(() => {
  for (const key of ENV_KEYS) saved[key] = process.env[key];
});
afterAll(() => {
  for (const key of ENV_KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
});

beforeEach(() => {
  jest.clearAllMocks();
  _resetLoginRateLimit();
  process.env.SENDGRID_API_KEY = 'SG.key';
  process.env.EMAIL_FROM = 'no-reply@apiome.dev';
  process.env.BETTER_AUTH_URL = 'https://app.apiome.dev';
  delete process.env.TURNSTILE_SITE_KEY;
  delete process.env.TURNSTILE_SECRET_KEY;
  mockRecordSignupGuardEvent.mockResolvedValue(undefined);
  mockResolveSignupPolicy.mockResolvedValue(OPEN);
  mockSendSignupEmail.mockResolvedValue(true);
  mockIssueVerificationToken.mockResolvedValue(undefined);
  mockFindPendingSignup.mockResolvedValue(null);
  mockCreateUser.mockResolvedValue(JSON.stringify({ success: true }));
});

describe('startEmailSignup', () => {
  it('creates an unverified account under the canonical email and sends a verification link', async () => {
    mockFindSignupAccount.mockResolvedValueOnce(null).mockResolvedValueOnce(NEW_ACCOUNT);

    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });

    expect(mockFindSignupAccount).toHaveBeenCalledWith('ada@example.com');
    // The account is created with this sign-up's bcrypt hash, never the plain password…
    const [createdName, createdEmail, createdHash, createdVerified] = mockCreateUser.mock.calls[0];
    expect([createdName, createdEmail, createdVerified]).toEqual(['Ada Lovelace', 'ada@example.com', false]);
    expect(bcrypt.compareSync('Analytical1', createdHash)).toBe(true);
    // …and the link is bound to that same hash and name.
    const [userId, tokenHash, expiresAt, pending] = mockIssueVerificationToken.mock.calls[0];
    expect(pending).toEqual({ passwordHash: createdHash, name: 'Ada Lovelace' });
    expect(userId).toBe('u-1');
    expect(tokenHash).toMatch(/^[0-9a-f]{64}$/);
    expect((expiresAt as Date).getTime() - Date.now()).toBeGreaterThan(23.9 * 60 * 60 * 1000);
    const [to, message] = mockSendSignupEmail.mock.calls[0];
    expect(to).toBe('ada@example.com');
    expect(message.subject).toBe('Confirm your email for Apiome');
    expect(message.text).toMatch(/https:\/\/app\.apiome\.dev\/signup\/verify\?token=[A-Za-z0-9_-]{43}/);
  });

  it('answers an existing, confirmed address exactly like a new one, and emails the owner', async () => {
    mockFindSignupAccount.mockResolvedValue({ ...NEW_ACCOUNT, verified: true });

    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });

    expect(mockCreateUser).not.toHaveBeenCalled();
    expect(mockIssueVerificationToken).not.toHaveBeenCalled();
    expect(mockSendSignupEmail.mock.calls[0][1].subject).toBe('You already have an Apiome account');
    expect(mockSendSignupEmail.mock.calls[0][1].text).toContain('https://app.apiome.dev/login');
  });

  it('binds the new link to *this* sign-up’s password for an existing, unconfirmed address (pre-hijacking fix)', async () => {
    // Someone signed up with this address first; the owner now signs up with their own password.
    mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
    await expect(startEmailSignup({ ...GOOD, name: 'Ada (owner)', password: 'Different9' })).resolves.toEqual({
      ok: true,
    });
    expect(mockCreateUser).not.toHaveBeenCalled();
    expect(mockIssueVerificationToken).toHaveBeenCalledTimes(1);
    const pending = mockIssueVerificationToken.mock.calls[0][3];
    expect(pending.name).toBe('Ada (owner)');
    expect(bcrypt.compareSync('Different9', pending.passwordHash)).toBe(true);
    expect(mockSendSignupEmail.mock.calls[0][1].subject).toBe('Confirm your email for Apiome');
  });

  it('sends nothing for a disabled account, and still answers ok', async () => {
    mockFindSignupAccount.mockResolvedValue({ ...NEW_ACCOUNT, verified: true, enabled: false });
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });
    expect(mockSendSignupEmail).not.toHaveBeenCalled();
  });

  it('treats a lost race on the unique email as an existing address', async () => {
    mockFindSignupAccount.mockResolvedValueOnce(null).mockResolvedValueOnce({ ...NEW_ACCOUNT, verified: true });
    mockCreateUser.mockResolvedValue(JSON.stringify({ success: false, error: 'duplicate key' }));
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });
    expect(mockSendSignupEmail.mock.calls[0][1].subject).toBe('You already have an Apiome account');
  });

  it('logs why the account could not be created, without the address', async () => {
    // Before V319 a deleted account still held its address, so createUser refused and the log said
    // only "Error".
    const error = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockFindSignupAccount.mockResolvedValue(null);
    mockCreateUser.mockResolvedValue(
      JSON.stringify({ success: false, error: 'User with this email already exists: ada@example.com' })
    );
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: false, code: 'email-signup-send-failed' });
    expect(error).toHaveBeenCalledWith(
      '[email-signup] sign-up failed:',
      'Error: user insert failed: User with this email already exists: <email>'
    );
    error.mockRestore();
  });

  it.each([
    ['closed', { mode: 'closed', allowedEmailDomains: [], source: 'db' }, 'signup-disabled'],
    ['invite-only', { mode: 'invite_only', allowedEmailDomains: [], source: 'db' }, 'signup-invite-only'],
    ['another domain', { mode: 'open', allowedEmailDomains: ['northwind.io'], source: 'db' }, 'signup-domain-not-allowed'],
  ])('refuses under the %s policy before looking the address up', async (_label, policy, code) => {
    mockResolveSignupPolicy.mockResolvedValue(policy);
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: false, code });
    // The refusal never depends on whether the address has an account.
    expect(mockFindSignupAccount).not.toHaveBeenCalled();
    expect(mockSendSignupEmail).not.toHaveBeenCalled();
  });

  it.each(['SENDGRID_API_KEY', 'EMAIL_FROM', 'BETTER_AUTH_URL'])('is unavailable without %s', async (key) => {
    delete process.env[key];
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: false, code: 'email-signup-unavailable' });
    expect(mockCreateUser).not.toHaveBeenCalled();
  });

  it.each([
    [{ ...GOOD, name: '   ' }, 'Enter your name.'],
    [{ ...GOOD, name: 'x'.repeat(256) }, 'Enter your name.'],
    [{ ...GOOD, email: 'not-an-email' }, 'Enter a valid email address.'],
    [{ ...GOOD, email: 42 }, 'Enter a valid email address.'],
    [{ ...GOOD, password: 'short1A' }, 'Password must be at least 8 characters long.'],
    [{ ...GOOD, password: 'alllowercase1' }, 'Password must contain at least one uppercase letter.'],
  ])('refuses invalid input %#', async (input, message) => {
    await expect(startEmailSignup(input)).resolves.toEqual({ ok: false, code: 'email-signup-invalid', message });
    expect(mockFindSignupAccount).not.toHaveBeenCalled();
  });

  it('caps the emails one address can trigger', async () => {
    mockFindSignupAccount.mockResolvedValue({ ...NEW_ACCOUNT, verified: true });
    for (let i = 0; i < 3; i += 1) await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: false, code: 'email-signup-rate-limited' });
    expect(mockSendSignupEmail).toHaveBeenCalledTimes(3);
  });

  it('reports a refused send the same way for new and existing addresses', async () => {
    mockSendSignupEmail.mockResolvedValue(false);
    mockFindSignupAccount.mockResolvedValueOnce(null).mockResolvedValueOnce(NEW_ACCOUNT);
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: false, code: 'email-signup-send-failed' });
    mockFindSignupAccount.mockReset().mockResolvedValue({ ...NEW_ACCOUNT, email: 'b@example.com', verified: true });
    await expect(startEmailSignup({ ...GOOD, email: 'b@example.com' })).resolves.toEqual({
      ok: false,
      code: 'email-signup-send-failed',
    });
  });
});

describe('startEmailSignup — abuse guards (SGN-1.5)', () => {
  /** The guard events recorded so far, without the request headers. */
  const events = () =>
    mockRecordSignupGuardEvent.mock.calls.map(([event]) => {
      const rest = { ...(event as Record<string, unknown>) };
      delete rest.headers;
      return rest;
    });

  it.each(['bot@mailinator.com', 'bot@inbox.mailinator.com', 'BOT@YopMail.com'])(
    'refuses the disposable address %s before looking it up, and records it',
    async (email) => {
      await expect(startEmailSignup({ ...GOOD, email })).resolves.toEqual({
        ok: false,
        code: 'email-signup-disposable-domain',
      });
      expect(mockFindSignupAccount).not.toHaveBeenCalled();
      expect(mockSendSignupEmail).not.toHaveBeenCalled();
      expect(events()).toEqual([
        {
          guard: 'disposable_domain',
          code: 'email-signup-disposable-domain',
          scope: undefined,
          email: email.toLowerCase(),
          provider: 'email',
        },
      ]);
    }
  );

  it('refuses a domain the admin added to the blocklist', async () => {
    mockResolveSignupPolicy.mockResolvedValue({ ...OPEN, blockedEmailDomains: ['example.com'] });
    await expect(startEmailSignup(GOOD)).resolves.toEqual({
      ok: false,
      code: 'email-signup-disposable-domain',
    });
  });

  it('lets an ordinary address through and records nothing', async () => {
    mockFindSignupAccount.mockResolvedValueOnce(null).mockResolvedValueOnce(NEW_ACCOUNT);
    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });
    expect(mockRecordSignupGuardEvent).not.toHaveBeenCalled();
    // CAPTCHA is off by default: Cloudflare is never asked.
    expect(mockVerifyTurnstileToken).not.toHaveBeenCalled();
  });

  it('records an address rate limit once per window', async () => {
    mockFindSignupAccount.mockResolvedValue({ ...NEW_ACCOUNT, verified: true });
    for (let i = 0; i < 3; i += 1) await startEmailSignup(GOOD);
    for (let i = 0; i < 2; i += 1) {
      await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: false, code: 'email-signup-rate-limited' });
    }
    expect(events()).toEqual([
      {
        guard: 'rate_limit',
        code: 'email-signup-rate-limited',
        scope: 'address',
        email: 'ada@example.com',
        provider: 'email',
      },
    ]);
  });

  it('records an IP rate limit once per window, before reading the fields', async () => {
    // Different addresses, so only the per-IP budget (20 an hour) runs out.
    for (let i = 0; i < 20; i += 1) await startEmailSignup({ ...GOOD, name: '' });
    await expect(startEmailSignup({ ...GOOD, name: '' })).resolves.toEqual({
      ok: false,
      code: 'email-signup-rate-limited',
    });
    await startEmailSignup({ ...GOOD, name: '' });
    expect(events()).toEqual([
      expect.objectContaining({ guard: 'rate_limit', scope: 'ip', email: 'ada@example.com' }),
    ]);
  });

  describe('with Turnstile configured', () => {
    beforeEach(() => {
      process.env.TURNSTILE_SITE_KEY = '1x00000000000000000000AA';
      process.env.TURNSTILE_SECRET_KEY = '1x0000000000000000000000000000000AA';
    });

    it('refuses a token Cloudflare does not confirm, and records it', async () => {
      mockVerifyTurnstileToken.mockResolvedValue(false);
      await expect(startEmailSignup({ ...GOOD, captchaToken: 'bad' })).resolves.toEqual({
        ok: false,
        code: 'email-signup-captcha-failed',
      });
      expect(mockVerifyTurnstileToken).toHaveBeenCalledWith(
        'bad',
        '1x0000000000000000000000000000000AA',
        '203.0.113.7'
      );
      expect(mockFindSignupAccount).not.toHaveBeenCalled();
      expect(events()).toEqual([
        expect.objectContaining({ guard: 'captcha', code: 'email-signup-captcha-failed' }),
      ]);
    });

    it('accepts a confirmed token', async () => {
      mockVerifyTurnstileToken.mockResolvedValue(true);
      mockFindSignupAccount.mockResolvedValueOnce(null).mockResolvedValueOnce(NEW_ACCOUNT);
      await expect(startEmailSignup({ ...GOOD, captchaToken: 'good' })).resolves.toEqual({ ok: true });
    });

    it('checks the fields first, so a typo does not spend the token', async () => {
      await expect(startEmailSignup({ ...GOOD, name: '', captchaToken: 'good' })).resolves.toMatchObject({
        code: 'email-signup-invalid',
      });
      expect(mockVerifyTurnstileToken).not.toHaveBeenCalled();
    });

    it('is off again when only one key is set', async () => {
      delete process.env.TURNSTILE_SECRET_KEY;
      mockFindSignupAccount.mockResolvedValueOnce(null).mockResolvedValueOnce(NEW_ACCOUNT);
      await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });
      expect(mockVerifyTurnstileToken).not.toHaveBeenCalled();
    });

    it('never asks for a CAPTCHA on Resend email', async () => {
      mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
      await expect(resendSignupVerification('ada@example.com')).resolves.toEqual({ ok: true });
      expect(mockVerifyTurnstileToken).not.toHaveBeenCalled();
    });
  });
});

describe('resendSignupVerification', () => {
  it('sends a fresh link to an unconfirmed account', async () => {
    mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
    await expect(resendSignupVerification('ADA@example.com')).resolves.toEqual({ ok: true });
    expect(mockFindSignupAccount).toHaveBeenCalledWith('ada@example.com');
    expect(mockIssueVerificationToken).toHaveBeenCalledTimes(1);
    expect(mockSendSignupEmail).toHaveBeenCalledTimes(1);
  });

  it('carries the newest sign-up’s pending password onto the resent link', async () => {
    const pending = { passwordHash: bcrypt.hashSync('Analytical1', 4), name: 'Ada Lovelace' };
    mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
    mockFindPendingSignup.mockResolvedValue(pending);
    await expect(resendSignupVerification('ada@example.com')).resolves.toEqual({ ok: true });
    expect(mockFindPendingSignup).toHaveBeenCalledWith('u-1');
    expect(mockIssueVerificationToken.mock.calls[0][3]).toEqual(pending);
  });

  it.each([
    ['an unknown address', null],
    ['a confirmed account', { ...NEW_ACCOUNT, verified: true }],
    ['a disabled account', { ...NEW_ACCOUNT, enabled: false }],
  ])('answers ok and sends nothing for %s', async (_label, account) => {
    mockFindSignupAccount.mockResolvedValue(account);
    await expect(resendSignupVerification('ada@example.com')).resolves.toEqual({ ok: true });
    expect(mockSendSignupEmail).not.toHaveBeenCalled();
  });

  it('is rate-limited per address, and records the refusal', async () => {
    mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
    for (let i = 0; i < 3; i += 1) await resendSignupVerification('ada@example.com');
    await expect(resendSignupVerification('ada@example.com')).resolves.toEqual({
      ok: false,
      code: 'email-signup-rate-limited',
    });
    expect(mockSendSignupEmail).toHaveBeenCalledTimes(3);
    expect(mockRecordSignupGuardEvent).toHaveBeenCalledTimes(1);
    expect(mockRecordSignupGuardEvent.mock.calls[0][0]).toMatchObject({
      guard: 'rate_limit',
      scope: 'address',
      email: 'ada@example.com',
    });
  });

  it('refuses a malformed address and is unavailable without a sender', async () => {
    await expect(resendSignupVerification('nope')).resolves.toMatchObject({ ok: false, code: 'email-signup-invalid' });
    delete process.env.SENDGRID_API_KEY;
    await expect(resendSignupVerification('ada@example.com')).resolves.toEqual({
      ok: false,
      code: 'email-signup-unavailable',
    });
  });
});

describe('verifyEmailSignup', () => {
  const TOKEN = 'a'.repeat(43);

  const PASSWORD = 'Analytical1';

  it('refuses a malformed token without touching the database', async () => {
    await expect(verifyEmailSignup({ token: '../etc', password: PASSWORD })).resolves.toEqual({ state: 'invalid' });
    expect(mockRedeemVerificationToken).not.toHaveBeenCalled();
  });

  it('asks for the password before touching the database', async () => {
    await expect(verifyEmailSignup({ token: TOKEN, password: '' })).resolves.toEqual({ state: 'password-mismatch' });
    await expect(verifyEmailSignup({ token: TOKEN, password: 42 })).resolves.toEqual({ state: 'password-mismatch' });
    expect(mockRedeemVerificationToken).not.toHaveBeenCalled();
  });

  it('redeems a valid link with its password into a workspace-less one-time sign-in code', async () => {
    mockRedeemVerificationToken.mockResolvedValue({ state: 'valid', userId: 'u-1' });
    mockInsertAuthOneTimeCode.mockResolvedValue('code-1');
    await expect(verifyEmailSignup({ token: TOKEN, password: PASSWORD })).resolves.toEqual({
      state: 'valid',
      oneTimeCode: 'code-1',
    });
    expect(mockRedeemVerificationToken.mock.calls[0][0]).toMatch(/^[0-9a-f]{64}$/);
    expect(mockRedeemVerificationToken.mock.calls[0][1]).toBe(PASSWORD);
    expect(mockInsertAuthOneTimeCode).toHaveBeenCalledWith('u-1', null);
  });

  it('passes a wrong password through without signing in', async () => {
    mockRedeemVerificationToken.mockResolvedValue({ state: 'password-mismatch', userId: null });
    await expect(verifyEmailSignup({ token: TOKEN, password: 'Attacker#Pass1' })).resolves.toEqual({
      state: 'password-mismatch',
    });
    expect(mockInsertAuthOneTimeCode).not.toHaveBeenCalled();
  });

  it.each(['expired', 'used', 'invalid'] as const)('passes a %s link through without signing in', async (state) => {
    mockRedeemVerificationToken.mockResolvedValue({ state, userId: null });
    await expect(verifyEmailSignup({ token: TOKEN, password: PASSWORD })).resolves.toEqual({ state });
    expect(mockInsertAuthOneTimeCode).not.toHaveBeenCalled();
  });

  it('fails closed when the database throws', async () => {
    mockRedeemVerificationToken.mockRejectedValue(new Error('down'));
    await expect(verifyEmailSignup({ token: TOKEN, password: PASSWORD })).resolves.toEqual({ state: 'invalid' });
  });
});
