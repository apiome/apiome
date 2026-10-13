import {
  canonicalizeCrossAppCallback,
  getSharedCookieDomain,
  isAllowedCallbackUrl,
  isSafeRelativeCallbackPath,
  resolveCallbackUrl,
} from '@lib/auth/cookie-options';

describe('cookie-options', () => {
  const env = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...env };
  });

  afterAll(() => {
    process.env = env;
  });

  it('infers the shared cookie domain from BETTER_AUTH_URL in production', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
    process.env.BETTER_AUTH_URL = 'https://main.apiome.dev';

    expect(getSharedCookieDomain()).toBe('.apiome.dev');
  });

  it('allows studio callbacks when the studio URL is configured', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
    process.env.BETTER_AUTH_URL = 'https://main.apiome.dev';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://suite.apiome.dev';

    const callback = 'https://suite.apiome.dev/editor';
    expect(isAllowedCallbackUrl(callback, process.env.BETTER_AUTH_URL)).toBe(true);
    expect(resolveCallbackUrl(callback)).toBe(callback);
  });

  it('allows studio callbacks from the inferred cookie domain without an explicit studio env', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
    delete process.env.NEXT_PUBLIC_STUDIO_URL;
    process.env.BETTER_AUTH_URL = 'https://main.apiome.dev';

    const callback = 'https://suite.apiome.dev/editor';
    expect(resolveCallbackUrl(callback)).toBe(callback);
  });

  it('rejects callbacks outside the deployment domain', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
    process.env.BETTER_AUTH_URL = 'https://main.apiome.dev';

    expect(resolveCallbackUrl('https://evil.example/phish')).toBe('/ade');
  });

  it('ignores a stale cookie domain that does not match the deployment hostnames', () => {
    process.env.NODE_ENV = 'production';
    process.env.BETTER_AUTH_COOKIE_DOMAIN = '.apiome.dev';
    process.env.BETTER_AUTH_URL = 'https://main.apiome.dev';

    expect(getSharedCookieDomain()).toBe('.apiome.dev');
    expect(resolveCallbackUrl('https://suite.apiome.dev/editor')).toBe(
      'https://suite.apiome.dev/editor'
    );
  });

  it('rewrites stale studio hostnames to the configured studio origin', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
    process.env.BETTER_AUTH_URL = 'https://main.apiome.dev';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://suite.apiome.dev';

    const stale = 'https://studio.apiome.dev/editor';
    expect(canonicalizeCrossAppCallback(stale)).toBe('https://suite.apiome.dev/editor');
    expect(resolveCallbackUrl(stale)).toBe('https://suite.apiome.dev/editor');
  });

  // Open-redirect hardening (OLO-3.4, #4202): a callbackUrl must never be able
  // to leave the deployment. Browsers parse `\` as `/` in http(s) URLs, so a
  // redirect to `/\evil.com` resolves to https://evil.com/ — every relative
  // form that a browser could reinterpret as cross-origin must be rejected.
  describe('open-redirect rejection', () => {
    it('accepts ordinary same-origin relative paths', () => {
      expect(isSafeRelativeCallbackPath('/ade')).toBe(true);
      expect(isSafeRelativeCallbackPath('/ade/dashboard/projects?tab=all#top')).toBe(true);
      expect(isAllowedCallbackUrl('/ade/dashboard/projects?tab=all')).toBe(true);
    });

    it('rejects protocol-relative URLs', () => {
      expect(isSafeRelativeCallbackPath('//evil.example')).toBe(false);
      expect(isAllowedCallbackUrl('//evil.example')).toBe(false);
      expect(resolveCallbackUrl('//evil.example')).toBe('/ade');
    });

    it('rejects backslash protocol-relative equivalents', () => {
      for (const vector of ['/\\evil.example', '/\\/evil.example', '\\/evil.example', '\\\\evil.example']) {
        expect(isSafeRelativeCallbackPath(vector)).toBe(false);
        expect(isAllowedCallbackUrl(vector)).toBe(false);
        expect(resolveCallbackUrl(vector)).toBe('/ade');
      }
    });

    it('rejects backslashes anywhere in a relative path', () => {
      expect(isSafeRelativeCallbackPath('/ade/..\\..\\evil')).toBe(false);
      expect(isAllowedCallbackUrl('/ade/..\\..\\evil')).toBe(false);
    });

    it('rejects non-relative non-URL junk', () => {
      expect(isAllowedCallbackUrl('javascript:alert(1)')).toBe(false);
      expect(resolveCallbackUrl('javascript:alert(1)')).toBe('/ade');
      expect(resolveCallbackUrl('   ')).toBe('/ade');
      expect(resolveCallbackUrl(null)).toBe('/ade');
      expect(resolveCallbackUrl(undefined)).toBe('/ade');
    });

    it('rejects external absolute URLs in production regardless of scheme', () => {
      process.env.NODE_ENV = 'production';
      process.env.BETTER_AUTH_URL = 'https://main.apiome.dev';

      expect(resolveCallbackUrl('https://evil.example/phish')).toBe('/ade');
      expect(resolveCallbackUrl('http://main.apiome.dev.evil.example/')).toBe('/ade');
    });
  });

  // Public Suffix List (OLO-7.3 follow-up, #4961): the deployment boundary is the registrable
  // domain, not "the last two labels". On a multi-label public suffix — a platform preview host or
  // a country-code second level — the last two labels are the suffix itself, shared with strangers.
  describe.each([
    ['a platform preview host (vercel.app)', 'apiome.vercel.app', 'attacker.vercel.app', '.apiome.vercel.app'],
    ['a platform preview host (pages.dev)', 'apiome.pages.dev', 'attacker.pages.dev', '.apiome.pages.dev'],
    ['a platform preview host (github.io)', 'apiome.github.io', 'attacker.github.io', '.apiome.github.io'],
    ['a multi-label country suffix (co.uk)', 'app.example.co.uk', 'attacker.co.uk', '.example.co.uk'],
  ])('deployed on %s', (_name, appHost, attackerHost, cookieDomain) => {
    beforeEach(() => {
      process.env.NODE_ENV = 'production';
      delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
      delete process.env.NEXT_PUBLIC_STUDIO_URL;
      delete process.env.NEXT_PUBLIC_MAIN_APP_URL;
      process.env.BETTER_AUTH_URL = `https://${appHost}`;
    });

    it('rejects a callback to another tenant of the same public suffix', () => {
      const callback = `https://${attackerHost}/phish`;
      expect(isAllowedCallbackUrl(callback, process.env.BETTER_AUTH_URL)).toBe(false);
      expect(resolveCallbackUrl(callback)).toBe('/ade');
      expect(canonicalizeCrossAppCallback(callback)).toBe(callback);
    });

    it('scopes the session cookie to the registrable domain, not the suffix', () => {
      expect(getSharedCookieDomain()).toBe(cookieDomain);
    });

    it('still allows the app itself and its own subdomains', () => {
      expect(resolveCallbackUrl(`https://${appHost}/ade`)).toBe(`https://${appHost}/ade`);
      const own = `https://preview.${cookieDomain.slice(1)}/editor`;
      expect(resolveCallbackUrl(own)).toBe(own);
    });

    it('ignores a configured cookie domain that is the public suffix itself', () => {
      process.env.BETTER_AUTH_COOKIE_DOMAIN = `.${attackerHost.split('.').slice(1).join('.')}`;
      expect(getSharedCookieDomain()).toBe(cookieDomain);
      expect(resolveCallbackUrl(`https://${attackerHost}/phish`)).toBe('/ade');
    });
  });

  it('does not trust a sibling app on the same platform suffix unless it is configured', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
    delete process.env.NEXT_PUBLIC_MAIN_APP_URL;
    process.env.BETTER_AUTH_URL = 'https://apiome.vercel.app';
    delete process.env.NEXT_PUBLIC_STUDIO_URL;

    const studio = 'https://apiome-studio.vercel.app/editor';
    expect(resolveCallbackUrl(studio)).toBe('/ade');

    // Naming the studio origin explicitly is what trusts it — exact origin, nothing wider.
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://apiome-studio.vercel.app';
    expect(resolveCallbackUrl(studio)).toBe(studio);
    expect(resolveCallbackUrl('https://apiome-studio2.vercel.app/editor')).toBe('/ade');
  });

  it('applies no shared cookie domain when the only configured domain is a public suffix', () => {
    process.env.NODE_ENV = 'production';
    process.env.BETTER_AUTH_COOKIE_DOMAIN = '.co.uk';
    delete process.env.BETTER_AUTH_URL;
    delete process.env.NEXT_PUBLIC_STUDIO_URL;
    delete process.env.NEXT_PUBLIC_MAIN_APP_URL;

    expect(getSharedCookieDomain()).toBeUndefined();
    expect(isAllowedCallbackUrl('https://attacker.co.uk/phish')).toBe(false);
  });

  it('keeps an internal deployment on an unlisted suffix working', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.BETTER_AUTH_COOKIE_DOMAIN;
    delete process.env.NEXT_PUBLIC_STUDIO_URL;
    delete process.env.NEXT_PUBLIC_MAIN_APP_URL;
    process.env.BETTER_AUTH_URL = 'https://app.apiome.corp';

    expect(getSharedCookieDomain()).toBe('.apiome.corp');
    expect(resolveCallbackUrl('https://studio.apiome.corp/editor')).toBe('https://studio.apiome.corp/editor');
    expect(resolveCallbackUrl('https://app.other.corp/')).toBe('/ade');
  });

  it('does not apply a production cookie domain on localhost', () => {
    process.env.NODE_ENV = 'development';
    process.env.BETTER_AUTH_COOKIE_DOMAIN = '.apiome.dev';
    process.env.BETTER_AUTH_URL = 'http://localhost:3000';

    expect(getSharedCookieDomain()).toBeUndefined();
  });
});
