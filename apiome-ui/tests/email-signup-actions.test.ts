/**
 * Email sign-up server actions (SGN-1.1, #5650): the policy gate, no enumeration, canonicalization,
 * the no-sender path, per-address budgets, resend and link redemption.
 */

const mockFindSignupAccount = jest.fn();
const mockIssueVerificationToken = jest.fn();
const mockRedeemVerificationToken = jest.fn();
const mockCreateUser = jest.fn();
const mockInsertAuthOneTimeCode = jest.fn();
const mockSendSignupEmail = jest.fn();
const mockResolveSignupPolicy = jest.fn();

jest.mock('next/headers', () => ({
  headers: async () => new Headers({ 'x-forwarded-for': '203.0.113.7' }),
}));
jest.mock('../lib/db/email-verification', () => ({
  findSignupAccount: (...args: unknown[]) => mockFindSignupAccount(...args),
  issueVerificationToken: (...args: unknown[]) => mockIssueVerificationToken(...args),
  redeemVerificationToken: (...args: unknown[]) => mockRedeemVerificationToken(...args),
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

import {
  resendSignupVerification,
  startEmailSignup,
  verifyEmailSignup,
} from '../lib/auth/email-signup-actions';
import { _resetLoginRateLimit } from '../lib/auth/login-rate-limit';

const ENV_KEYS = ['SENDGRID_API_KEY', 'EMAIL_FROM', 'BETTER_AUTH_URL'] as const;
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
  mockResolveSignupPolicy.mockResolvedValue(OPEN);
  mockSendSignupEmail.mockResolvedValue(true);
  mockIssueVerificationToken.mockResolvedValue(undefined);
  mockCreateUser.mockResolvedValue(JSON.stringify({ success: true }));
});

describe('startEmailSignup', () => {
  it('creates an unverified account under the canonical email and sends a verification link', async () => {
    mockFindSignupAccount.mockResolvedValueOnce(null).mockResolvedValueOnce(NEW_ACCOUNT);

    await expect(startEmailSignup(GOOD)).resolves.toEqual({ ok: true });

    expect(mockFindSignupAccount).toHaveBeenCalledWith('ada@example.com');
    expect(mockCreateUser).toHaveBeenCalledWith('Ada Lovelace', 'ada@example.com', 'Analytical1', false);
    const [userId, tokenHash, expiresAt] = mockIssueVerificationToken.mock.calls[0];
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

  it('re-sends a link to an existing, unconfirmed address without touching its password', async () => {
    mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
    await expect(startEmailSignup({ ...GOOD, password: 'Different9' })).resolves.toEqual({ ok: true });
    expect(mockCreateUser).not.toHaveBeenCalled();
    expect(mockIssueVerificationToken).toHaveBeenCalledTimes(1);
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

describe('resendSignupVerification', () => {
  it('sends a fresh link to an unconfirmed account', async () => {
    mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
    await expect(resendSignupVerification('ADA@example.com')).resolves.toEqual({ ok: true });
    expect(mockFindSignupAccount).toHaveBeenCalledWith('ada@example.com');
    expect(mockIssueVerificationToken).toHaveBeenCalledTimes(1);
    expect(mockSendSignupEmail).toHaveBeenCalledTimes(1);
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

  it('is rate-limited per address', async () => {
    mockFindSignupAccount.mockResolvedValue(NEW_ACCOUNT);
    for (let i = 0; i < 3; i += 1) await resendSignupVerification('ada@example.com');
    await expect(resendSignupVerification('ada@example.com')).resolves.toEqual({
      ok: false,
      code: 'email-signup-rate-limited',
    });
    expect(mockSendSignupEmail).toHaveBeenCalledTimes(3);
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

  it('refuses a malformed token without touching the database', async () => {
    await expect(verifyEmailSignup('../etc')).resolves.toEqual({ state: 'invalid' });
    expect(mockRedeemVerificationToken).not.toHaveBeenCalled();
  });

  it('redeems a valid link into a workspace-less one-time sign-in code', async () => {
    mockRedeemVerificationToken.mockResolvedValue({ state: 'valid', userId: 'u-1' });
    mockInsertAuthOneTimeCode.mockResolvedValue('code-1');
    await expect(verifyEmailSignup(TOKEN)).resolves.toEqual({ state: 'valid', oneTimeCode: 'code-1' });
    expect(mockRedeemVerificationToken.mock.calls[0][0]).toMatch(/^[0-9a-f]{64}$/);
    expect(mockInsertAuthOneTimeCode).toHaveBeenCalledWith('u-1', null);
  });

  it.each(['expired', 'used', 'invalid'] as const)('passes a %s link through without signing in', async (state) => {
    mockRedeemVerificationToken.mockResolvedValue({ state, userId: null });
    await expect(verifyEmailSignup(TOKEN)).resolves.toEqual({ state });
    expect(mockInsertAuthOneTimeCode).not.toHaveBeenCalled();
  });

  it('fails closed when the database throws', async () => {
    mockRedeemVerificationToken.mockRejectedValue(new Error('down'));
    await expect(verifyEmailSignup(TOKEN)).resolves.toEqual({ state: 'invalid' });
  });
});
