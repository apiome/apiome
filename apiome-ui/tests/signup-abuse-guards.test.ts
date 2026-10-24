/**
 * Sign-up abuse-guard building blocks (SGN-1.5, #5654): the disposable-email blocklist, the
 * Turnstile config and token check, the `auth_events` row a refusal leaves, the request budget's
 * once-per-window refusal flag, and the admin blocked-attempts proxy.
 */
import {
  BUNDLED_DISPOSABLE_EMAIL_DOMAINS,
  isDisposableEmail,
} from '../lib/auth/disposable-email-domains';
import { _resetLoginRateLimit, checkRequestBudget } from '../lib/auth/login-rate-limit';
import { recordSignupGuardEvent, signupGuardAuthEvent } from '../lib/auth/signup-guard-events';
import {
  TURNSTILE_VERIFY_URL,
  turnstileConfig,
  turnstileSiteKey,
  verifyTurnstileToken,
} from '../lib/auth/turnstile';
import { proxyListBlockedSignupAttempts } from '../lib/auth/admin-signup-policy-proxy';
import { blockedAttemptPath, blockedAttemptReason } from '../lib/auth/admin-signup-policy';
import { normalizeEmailDomain } from '../lib/auth/signup-policy';

describe('isDisposableEmail', () => {
  it('ships a sorted, de-duplicated list of valid bare domains', () => {
    expect(BUNDLED_DISPOSABLE_EMAIL_DOMAINS.length).toBeGreaterThan(50);
    expect(new Set(BUNDLED_DISPOSABLE_EMAIL_DOMAINS).size).toBe(BUNDLED_DISPOSABLE_EMAIL_DOMAINS.length);
    expect([...BUNDLED_DISPOSABLE_EMAIL_DOMAINS].sort()).toEqual(BUNDLED_DISPOSABLE_EMAIL_DOMAINS);
    for (const domain of BUNDLED_DISPOSABLE_EMAIL_DOMAINS) expect(normalizeEmailDomain(domain)).toBe(domain);
  });

  it.each([
    ['bot@mailinator.com', true],
    ['bot@inbox.mailinator.com', true],
    ['bot@Guerrillamail.com', true],
    ['ada@example.com', false],
    ['ada@gmail.com', false],
    // A suffix that is not a parent domain is not a match.
    ['ada@notmailinator.com', false],
    ['no-domain', false],
    ['trailing@', false],
  ])('%s → %s', (email, expected) => {
    expect(isDisposableEmail(email.toLowerCase())).toBe(expected);
  });

  it('adds the admin\'s extra domains, subdomains included', () => {
    expect(isDisposableEmail('ada@throwaway.example', ['throwaway.example'])).toBe(true);
    expect(isDisposableEmail('ada@a.throwaway.example', ['throwaway.example'])).toBe(true);
    expect(isDisposableEmail('ada@example.com', ['throwaway.example'])).toBe(false);
  });
});

describe('turnstileConfig', () => {
  it('is on only when both keys are set', () => {
    expect(turnstileConfig({})).toBeNull();
    expect(turnstileConfig({ TURNSTILE_SITE_KEY: 'site' })).toBeNull();
    expect(turnstileConfig({ TURNSTILE_SECRET_KEY: 'secret' })).toBeNull();
    expect(turnstileConfig({ TURNSTILE_SITE_KEY: ' site ', TURNSTILE_SECRET_KEY: ' ' })).toBeNull();
    expect(turnstileConfig({ TURNSTILE_SITE_KEY: ' site ', TURNSTILE_SECRET_KEY: 'secret' })).toEqual({
      siteKey: 'site',
      secretKey: 'secret',
    });
  });

  it('hands the browser the site key, never the secret', () => {
    expect(turnstileSiteKey({ TURNSTILE_SITE_KEY: 'site', TURNSTILE_SECRET_KEY: 'secret' })).toBe('site');
    expect(turnstileSiteKey({ TURNSTILE_SITE_KEY: 'site' })).toBeNull();
  });
});

describe('verifyTurnstileToken', () => {
  /** A fetch answering `body` with `status`. */
  const answering = (body: unknown, status = 200) =>
    jest.fn(async () => ({ ok: status < 300, status, json: async () => body })) as unknown as typeof fetch;

  it('asks Cloudflare with the secret, the token and the client IP', async () => {
    const fetchImpl = answering({ success: true });
    await expect(verifyTurnstileToken('tok', 'secret', '203.0.113.7', fetchImpl)).resolves.toBe(true);
    const [url, init] = (fetchImpl as unknown as jest.Mock).mock.calls[0];
    expect(url).toBe(TURNSTILE_VERIFY_URL);
    const body = init.body as URLSearchParams;
    expect([body.get('secret'), body.get('response'), body.get('remoteip')]).toEqual([
      'secret',
      'tok',
      '203.0.113.7',
    ]);
  });

  it('leaves out an unknown client IP', async () => {
    const fetchImpl = answering({ success: true });
    await verifyTurnstileToken('tok', 'secret', 'unknown', fetchImpl);
    expect(((fetchImpl as unknown as jest.Mock).mock.calls[0][1].body as URLSearchParams).has('remoteip')).toBe(
      false
    );
  });

  it.each([
    ['a rejected token', answering({ success: false })],
    ['a non-2xx answer', answering({ success: true }, 500)],
    ['a body without success', answering({})],
    ['a network error', jest.fn().mockRejectedValue(new Error('down')) as unknown as typeof fetch],
  ])('fails closed on %s', async (_label, fetchImpl) => {
    await expect(verifyTurnstileToken('tok', 'secret', null, fetchImpl)).resolves.toBe(false);
  });

  it.each([[undefined], [''], [42], ['x'.repeat(2049)]])('refuses %p without asking', async (token) => {
    const fetchImpl = answering({ success: true });
    await expect(verifyTurnstileToken(token, 'secret', null, fetchImpl)).resolves.toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe('signupGuardAuthEvent', () => {
  const headers = new Headers({ 'x-forwarded-for': '203.0.113.7, 10.0.0.1', 'user-agent': 'curl/8' });

  it('builds a failed sign_up row naming the guard', () => {
    expect(
      signupGuardAuthEvent({
        guard: 'rate_limit',
        scope: 'address',
        code: 'email-signup-rate-limited',
        provider: 'email',
        email: 'ada@example.com',
        headers,
      })
    ).toEqual({
      event_type: 'sign_up',
      outcome: 'failure',
      provider: 'email',
      user_label: 'ada@example.com',
      error_code: 'email-signup-rate-limited',
      ip: '203.0.113.7',
      user_agent: 'curl/8',
      detail: { guard: 'rate_limit', scope: 'address' },
    });
  });

  it('leaves out what it does not know', () => {
    const row = signupGuardAuthEvent({ guard: 'captcha', code: 'c', provider: null, headers: {} });
    expect(row).toMatchObject({ provider: null, user_label: null, ip: 'unknown', user_agent: null });
    expect(row.detail).toEqual({ guard: 'captcha' });
  });

  it('never rejects, even when the writer throws', async () => {
    const write = jest.fn().mockRejectedValue(new Error('boom'));
    await expect(
      recordSignupGuardEvent({ guard: 'captcha', code: 'c', provider: 'email', headers }, write)
    ).resolves.toBeUndefined();
    expect(write).toHaveBeenCalledTimes(1);
  });
});

describe('checkRequestBudget — firstRefusal', () => {
  beforeEach(() => _resetLoginRateLimit());

  it('flags only the first refused request of a window', () => {
    const now = 1_000;
    const flags = Array.from({ length: 5 }, () => checkRequestBudget('k', 2, 60_000, now).firstRefusal);
    expect(flags).toEqual([false, false, true, false, false]);
    // A new window starts the count again.
    expect(checkRequestBudget('k', 2, 60_000, now + 60_000).firstRefusal).toBe(false);
  });
});

describe('admin blocked-attempts helpers', () => {
  it('bounds the limit it forwards', async () => {
    const fetchImpl = jest.fn(async () => ({ ok: true, status: 200, json: async () => ({ attempts: [] }) }));
    for (const limit of [0, 500, Number.NaN, 20]) {
      await proxyListBlockedSignupAttempts('token', limit, fetchImpl as unknown as typeof fetch);
    }
    const urls = fetchImpl.mock.calls.map((call) => String((call as unknown[])[0]));
    expect(urls.map((url) => url.split('?')[1])).toEqual(['limit=1', 'limit=200', 'limit=50', 'limit=20']);
    expect(urls[0]).toContain('/admin/signup-policy/blocked-attempts');
  });

  it('names each guard and path', () => {
    expect(blockedAttemptReason({ guard: 'rate_limit', scope: 'ip' })).toBe(
      'Rate limit — too many attempts from one network'
    );
    expect(blockedAttemptReason({ guard: 'rate_limit', scope: 'address' })).toBe(
      'Rate limit — too many emails to one address'
    );
    expect(blockedAttemptReason({ guard: 'disposable_domain', scope: null })).toBe('Disposable email address');
    expect(blockedAttemptReason({ guard: 'captcha', scope: null })).toBe('Security check failed');
    expect(blockedAttemptReason({ guard: 'future_guard', scope: null })).toBe('future_guard');
    expect([blockedAttemptPath('email'), blockedAttemptPath('github'), blockedAttemptPath(null)]).toEqual([
      'Email',
      'github',
      'Provider sign-up',
    ]);
  });
});
