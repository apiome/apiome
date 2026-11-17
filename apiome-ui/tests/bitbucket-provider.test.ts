/**
 * Bitbucket provider tests (OLO-9.9, #4992).
 *
 * Pins the slug on the linkable / auto-link sets and the display tables, and covers the pure
 * `/2.0/user/emails` resolution. Endpoint + end-to-end `getUserInfo` behaviour live in
 * `better-auth-oauth-providers.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';
import { PROVIDER_CRED_ENV_KEYS } from '../lib/auth/provider-config-resolver';
import { BITBUCKET_OAUTH_SCOPE, resolveBitbucketVerifiedEmail } from '../lib/auth/verified-email';
import {
  PAT_PROVIDERS,
  providerTagline,
} from '../src/app/components/ade/account/linkedAccountsModel';
import { getProviderBrand } from '../src/app/components/auth/provider-brand';

describe('Bitbucket provider (OLO-9.9)', () => {
  test('bitbucket is on the auto-link trust and linkable sets', () => {
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('bitbucket')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('bitbucket')).toBe(true);
  });

  test('admin-saved credentials overlay the Bitbucket env vars', () => {
    expect(PROVIDER_CRED_ENV_KEYS.bitbucket).toEqual({
      clientId: 'BITBUCKET_CLIENT_ID',
      clientSecret: 'BITBUCKET_CLIENT_SECRET',
    });
  });

  test('bitbucket has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('bitbucket')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('bitbucket')).toBe('Bitbucket Cloud account sign-in');
    expect(PAT_PROVIDERS.has('bitbucket')).toBe(false);
  });

  test('the scope asks for the profile and the emails API', () => {
    expect(BITBUCKET_OAUTH_SCOPE).toBe('account email');
  });
});

describe('resolveBitbucketVerifiedEmail', () => {
  const entry = (email: string, isPrimary: boolean, isConfirmed: boolean) => ({
    email,
    is_primary: isPrimary,
    is_confirmed: isConfirmed,
    type: 'email',
  });

  test('uses the primary address and its confirmed flag', () => {
    expect(
      resolveBitbucketVerifiedEmail({
        values: [entry('old@example.com', false, true), entry('ada@example.com', true, true)],
      })
    ).toEqual({ email: 'ada@example.com', emailVerified: true });
  });

  test('an unconfirmed primary surfaces the address as unverified', () => {
    expect(
      resolveBitbucketVerifiedEmail({
        values: [entry('old@example.com', false, true), entry('ada@example.com', true, false)],
      })
    ).toEqual({ email: 'ada@example.com', emailVerified: false });
  });

  test('a truthy but non-boolean confirmed flag is not trusted', () => {
    expect(
      resolveBitbucketVerifiedEmail({
        values: [{ email: 'ada@example.com', is_primary: true, is_confirmed: 'true' }],
      })
    ).toEqual({ email: 'ada@example.com', emailVerified: false });
  });

  test('no primary entry yields no email, even when a confirmed address exists', () => {
    expect(
      resolveBitbucketVerifiedEmail({ values: [entry('old@example.com', false, true)] })
    ).toEqual({ email: null, emailVerified: false });
  });

  test('a primary entry without a usable address is skipped', () => {
    expect(
      resolveBitbucketVerifiedEmail({
        values: [null, { is_primary: true, is_confirmed: true }, entry('  ', true, true)],
      })
    ).toEqual({ email: null, emailVerified: false });
  });

  test.each([null, undefined, {}, { values: 'nope' }, [], 'text'])(
    'malformed body %p fails closed',
    (body) => {
      expect(resolveBitbucketVerifiedEmail(body)).toEqual({ email: null, emailVerified: false });
    }
  );
});
