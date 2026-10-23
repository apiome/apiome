/**
 * Email sign-up — the pure parts (SGN-1.1, #5650): availability, tokens, link states and the two
 * emails.
 */
import {
  buildAccountExistsEmail,
  buildVerificationEmail,
  classifyVerificationToken,
  generateVerificationToken,
  hashVerificationToken,
  isEmailSignupAvailable,
  isWellFormedVerificationToken,
  publicBaseUrl,
  verificationLink,
} from '../lib/auth/email-signup';

const CONFIGURED = {
  SENDGRID_API_KEY: 'SG.key',
  EMAIL_FROM: 'Apiome <no-reply@apiome.dev>',
  BETTER_AUTH_URL: 'https://app.apiome.dev/',
};

describe('availability (the no-sender path)', () => {
  it('is on with a sender and a base URL', () => {
    expect(isEmailSignupAvailable(CONFIGURED)).toBe(true);
  });

  it.each(['SENDGRID_API_KEY', 'EMAIL_FROM', 'BETTER_AUTH_URL'])('is off without %s', (key) => {
    expect(isEmailSignupAvailable({ ...CONFIGURED, [key]: '   ' })).toBe(false);
    const without: Record<string, string> = { ...CONFIGURED };
    delete without[key];
    expect(isEmailSignupAvailable(without)).toBe(false);
  });

  it('is off when the base URL is not http(s)', () => {
    expect(isEmailSignupAvailable({ ...CONFIGURED, BETTER_AUTH_URL: 'javascript:alert(1)' })).toBe(false);
    expect(isEmailSignupAvailable({ ...CONFIGURED, BETTER_AUTH_URL: 'not a url' })).toBe(false);
  });

  it('normalizes the base URL without a trailing slash, keeping a path prefix', () => {
    expect(publicBaseUrl(CONFIGURED)).toBe('https://app.apiome.dev');
    expect(publicBaseUrl({ BETTER_AUTH_URL: 'https://example.com/apiome//' })).toBe('https://example.com/apiome');
  });
});

describe('tokens', () => {
  it('mints 43-character base64url tokens and stores only their SHA-256', () => {
    const { token, tokenHash } = generateVerificationToken();
    expect(isWellFormedVerificationToken(token)).toBe(true);
    expect(tokenHash).toMatch(/^[0-9a-f]{64}$/);
    expect(tokenHash).toBe(hashVerificationToken(token));
    expect(tokenHash).not.toContain(token);
    expect(generateVerificationToken().token).not.toBe(token);
  });

  it.each([undefined, '', 'short', 'x'.repeat(44), `${'a'.repeat(42)}=`, `${'a'.repeat(42)}/`])(
    'rejects the malformed token %p before any lookup',
    (token) => {
      expect(isWellFormedVerificationToken(token)).toBe(false);
    }
  );

  it('classifies a link: unknown, used, expired, valid', () => {
    const now = new Date('2026-10-23T12:00:00Z');
    expect(classifyVerificationToken(null, now)).toBe('invalid');
    expect(
      classifyVerificationToken({ expiresAt: new Date('2026-10-24T00:00:00Z'), usedAt: new Date('2026-10-23T11:00:00Z') }, now)
    ).toBe('used');
    expect(classifyVerificationToken({ expiresAt: now, usedAt: null }, now)).toBe('expired');
    expect(classifyVerificationToken({ expiresAt: new Date('2026-10-23T12:00:01Z'), usedAt: null }, now)).toBe('valid');
  });

  it('builds the link on the configured base URL', () => {
    expect(verificationLink('https://app.apiome.dev', 'abc_DEF-123')).toBe(
      'https://app.apiome.dev/signup/verify?token=abc_DEF-123'
    );
  });
});

describe('the verification email', () => {
  const message = buildVerificationEmail({
    name: 'Ada',
    link: 'https://app.apiome.dev/signup/verify?token=t',
  });

  it('greets by name and carries the link in both bodies', () => {
    expect(message.subject).toBe('Confirm your email for Apiome');
    expect(message.text).toContain('Hello Ada,');
    expect(message.text).toContain('https://app.apiome.dev/signup/verify?token=t');
    expect(message.html).toContain('href="https://app.apiome.dev/signup/verify?token=t"');
    expect(message.text).toContain('expires in 24 hours');
  });

  it('escapes a hostile display name in the HTML body', () => {
    const hostile = buildVerificationEmail({ name: '<img src=x onerror=alert(1)>', link: 'https://a.dev/x' });
    expect(hostile.html).not.toContain('<img');
    expect(hostile.html).toContain('&lt;img src=x onerror=alert(1)&gt;');
  });

  it('greets plainly with no name', () => {
    expect(buildVerificationEmail({ name: '  ', link: 'https://a.dev/x' }).text).toMatch(/^Hello,/);
  });
});

describe('the account-exists email', () => {
  it('says the account exists and links to sign-in, never to a verification link', () => {
    const message = buildAccountExistsEmail({ name: 'Ada', signInUrl: 'https://app.apiome.dev/login' });
    expect(message.subject).toBe('You already have an Apiome account');
    expect(message.text).toContain('you already have one');
    expect(message.text).toContain('https://app.apiome.dev/login');
    expect(message.html).toContain('href="https://app.apiome.dev/login"');
    expect(message.text).not.toContain('/signup/verify');
  });
});
