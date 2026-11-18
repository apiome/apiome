/**
 * X / Twitter provider smoke tests (OLO-9.32, #5045).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: X shares the email only
 * with the `users.email` scope, often not at all, and Apiome does not trust it, so X is
 * `link-first` under the OLO-9.16 trust-gate rule (#5029) and its email must never auto-link or
 * create an account. Also pins the credential env keys and the display tables, so a regression
 * that drops X from any of them fails loudly. Endpoint, no-email and fail-closed email behaviour
 * live in `better-auth-oauth-providers.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';
import { PROVIDER_EXTRA_FIELDS } from '../lib/auth/admin-provider-config';
import { PROVIDER_CRED_ENV_KEYS } from '../lib/auth/provider-config-resolver';
import { PROVIDER_TRUST_CLASSES, providerTrustClass } from '../lib/auth/provider-trust-classes';
import {
  PAT_PROVIDERS,
  providerTagline,
} from '../src/app/components/ade/account/linkedAccountsModel';
import { providerLabel } from '../src/app/components/ade/account/accountModel';
import { getProviderBrand } from '../src/app/components/auth/provider-brand';

describe('X / Twitter provider (OLO-9.32)', () => {
  test('twitter is link-first: linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('twitter')).toBe('link-first');
    expect(PROVIDER_TRUST_CLASSES.twitter.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('twitter')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('twitter')).toBe(true);
  });

  test('admin-saved credentials overlay the X env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.twitter).toEqual({
      clientId: 'TWITTER_CLIENT_ID',
      clientSecret: 'TWITTER_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.twitter).toBeUndefined();
  });

  test('twitter has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('twitter')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('twitter')).toBe('X (Twitter)');
    expect(providerTagline('twitter')).toBe('X account sign-in');
    expect(PAT_PROVIDERS.has('twitter')).toBe(false);
  });
});
