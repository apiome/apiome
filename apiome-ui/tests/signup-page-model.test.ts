/**
 * What `/signup` shows for each policy (SGN-1.2, #5651) and the legal-links reader.
 */
import {
  SIGNUP_CLOSED_NOTICE,
  SIGNUP_INVITE_ONLY_NOTICE,
  allowedDomainsHint,
  legalLinksFromEnv,
  signupPageState,
} from '../lib/auth/signup-page';

describe('signupPageState', () => {
  it('opens every path on an open installation with a mail sender', () => {
    expect(signupPageState({ mode: 'open', allowedEmailDomains: ['a.io'], source: 'db' }, true)).toEqual({
      mode: 'open',
      showProviders: true,
      showEmailForm: true,
      showEmailUnavailable: false,
      allowedDomains: ['a.io'],
      notice: null,
    });
  });

  it('swaps the form for the unavailable note without a mail sender', () => {
    const state = signupPageState({ mode: 'open', allowedEmailDomains: [], source: 'env' }, false);
    expect(state.showEmailForm).toBe(false);
    expect(state.showEmailUnavailable).toBe(true);
    expect(state.showProviders).toBe(true);
  });

  it.each([
    ['closed', SIGNUP_CLOSED_NOTICE],
    ['invite_only', SIGNUP_INVITE_ONLY_NOTICE],
  ] as const)('shows only the %s notice — no providers, no form, no domains', (mode, notice) => {
    expect(signupPageState({ mode, allowedEmailDomains: ['a.io'], source: 'db' }, true)).toEqual({
      mode,
      showProviders: false,
      showEmailForm: false,
      showEmailUnavailable: false,
      allowedDomains: [],
      notice,
    });
  });
});

describe('allowedDomainsHint', () => {
  it('reads naturally for one, two and many domains, and is absent for none', () => {
    expect(allowedDomainsHint([])).toBeNull();
    expect(allowedDomainsHint(['a.io'])).toBe('Sign-up is open to addresses at a.io.');
    expect(allowedDomainsHint(['a.io', 'b.io'])).toBe('Sign-up is open to addresses at a.io and b.io.');
    expect(allowedDomainsHint(['a.io', 'b.io', 'c.io'])).toBe('Sign-up is open to addresses at a.io, b.io and c.io.');
  });
});

describe('legalLinksFromEnv', () => {
  it('reads http(s) URLs and drops anything else', () => {
    expect(
      legalLinksFromEnv({ APIOME_TERMS_URL: ' https://apiome.dev/terms ', APIOME_PRIVACY_URL: 'javascript:alert(1)' })
    ).toEqual({ termsUrl: 'https://apiome.dev/terms', privacyUrl: null });
    expect(legalLinksFromEnv({})).toEqual({ termsUrl: null, privacyUrl: null });
    expect(legalLinksFromEnv({ APIOME_PRIVACY_URL: 'not a url' }).privacyUrl).toBeNull();
  });
});
