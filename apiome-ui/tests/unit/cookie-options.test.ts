import {
  buildAuthCookieOverrides,
  canonicalizeCrossAppCallback,
  getSharedCookieDomain,
  isAllowedCallbackUrl,
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

  it('infers the shared cookie domain from NEXTAUTH_URL in production', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.NEXTAUTH_COOKIE_DOMAIN;
    process.env.NEXTAUTH_URL = 'https://main.apiome.dev';

    expect(getSharedCookieDomain()).toBe('.apiome.dev');
    expect(buildAuthCookieOverrides().cookies.sessionToken.options.domain).toBe('.apiome.dev');
  });

  it('allows studio callbacks when the studio URL is configured', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.NEXTAUTH_COOKIE_DOMAIN;
    process.env.NEXTAUTH_URL = 'https://main.apiome.dev';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://suite.apiome.dev';

    const callback = 'https://suite.apiome.dev/editor';
    expect(isAllowedCallbackUrl(callback, process.env.NEXTAUTH_URL)).toBe(true);
    expect(resolveCallbackUrl(callback)).toBe(callback);
  });

  it('allows studio callbacks from the inferred cookie domain without an explicit studio env', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.NEXTAUTH_COOKIE_DOMAIN;
    delete process.env.NEXT_PUBLIC_STUDIO_URL;
    process.env.NEXTAUTH_URL = 'https://main.apiome.dev';

    const callback = 'https://suite.apiome.dev/editor';
    expect(resolveCallbackUrl(callback)).toBe(callback);
  });

  it('rejects callbacks outside the deployment domain', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.NEXTAUTH_COOKIE_DOMAIN;
    process.env.NEXTAUTH_URL = 'https://main.apiome.dev';

    expect(resolveCallbackUrl('https://evil.example/phish')).toBe('/ade');
  });

  it('ignores a stale cookie domain that does not match the deployment hostnames', () => {
    process.env.NODE_ENV = 'production';
    process.env.NEXTAUTH_COOKIE_DOMAIN = '.apiome.app';
    process.env.NEXTAUTH_URL = 'https://main.apiome.dev';

    expect(getSharedCookieDomain()).toBe('.apiome.dev');
    expect(resolveCallbackUrl('https://suite.apiome.dev/editor')).toBe(
      'https://suite.apiome.dev/editor'
    );
  });

  it('rewrites stale studio hostnames to the configured studio origin', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.NEXTAUTH_COOKIE_DOMAIN;
    process.env.NEXTAUTH_URL = 'https://main.apiome.dev';
    process.env.NEXT_PUBLIC_STUDIO_URL = 'https://suite.apiome.dev';

    const stale = 'https://studio.apiome.dev/editor';
    expect(canonicalizeCrossAppCallback(stale)).toBe('https://suite.apiome.dev/editor');
    expect(resolveCallbackUrl(stale)).toBe('https://suite.apiome.dev/editor');
  });

  it('does not apply a production cookie domain on localhost', () => {
    process.env.NODE_ENV = 'development';
    process.env.NEXTAUTH_COOKIE_DOMAIN = '.apiome.dev';
    process.env.NEXTAUTH_URL = 'http://localhost:3000';

    expect(getSharedCookieDomain()).toBeUndefined();
    expect(buildAuthCookieOverrides().cookies.sessionToken.options.domain).toBeUndefined();
  });
});
