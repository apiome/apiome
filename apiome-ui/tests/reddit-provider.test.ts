/**
 * Reddit provider smoke tests (OLO-9.33, #5046).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: Reddit exposes
 * `has_verified_email` but no email address, so it is `link-only` under the OLO-9.16 trust-gate
 * rule (#5029) and can never auto-link or create an account. Also pins the credential env keys
 * and the display tables, so a regression that drops Reddit from any of them fails loudly.
 * Endpoint and no-email behaviour live in `better-auth-oauth-providers.test.ts`.
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

describe('Reddit provider (OLO-9.33)', () => {
  test('reddit is link-only: linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('reddit')).toBe('link-only');
    expect(PROVIDER_TRUST_CLASSES.reddit.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('reddit')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('reddit')).toBe(true);
  });

  test('admin-saved credentials overlay the Reddit env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.reddit).toEqual({
      clientId: 'REDDIT_CLIENT_ID',
      clientSecret: 'REDDIT_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.reddit).toBeUndefined();
  });

  test('reddit has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('reddit')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('reddit')).toBe('Reddit');
    expect(providerTagline('reddit')).toBe('Reddit account sign-in');
    expect(PAT_PROVIDERS.has('reddit')).toBe(false);
  });
});
