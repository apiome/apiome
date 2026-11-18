/**
 * Sign in with Apple provider smoke tests (OLO-9.30, #5043).
 *
 * Pins the slug on both the linkable and the auto-link trust sets: Apple's id token carries
 * `email_verified`, so it is `trusted` under the OLO-9.16 trust-gate rule (#5029). Also pins the
 * credential mapping — the sealed secret slot holds the `.p8` private key, the Team ID and Key ID
 * are admin extras — and the display tables, so a regression that drops Apple from any of them
 * fails loudly. The key, JWT and `form_post` bridge live in `apple-sign-in.test.ts`; endpoint and
 * email behaviour in `better-auth-oauth-providers.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';
import { PROVIDER_EXTRA_FIELDS, providerCredentialLabels } from '../lib/auth/admin-provider-config';
import { PROVIDER_CRED_ENV_KEYS } from '../lib/auth/provider-config-resolver';
import { PROVIDER_TRUST_CLASSES, providerTrustClass } from '../lib/auth/provider-trust-classes';
import {
  PAT_PROVIDERS,
  providerTagline,
} from '../src/app/components/ade/account/linkedAccountsModel';
import { providerLabel } from '../src/app/components/ade/account/accountModel';
import { getProviderBrand } from '../src/app/components/auth/provider-brand';

describe('Sign in with Apple provider (OLO-9.30)', () => {
  test('apple is trusted: linkable and auto-link trusted on a verified email', () => {
    expect(providerTrustClass('apple')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.apple.provisional).toBeUndefined();
    expect(PROVIDER_TRUST_CLASSES.apple.evidence).toContain('`email_verified` id-token claim');
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('apple')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('apple')).toBe(true);
  });

  test('the sealed secret is the .p8 private key; Team ID and Key ID are admin extras', () => {
    expect(PROVIDER_CRED_ENV_KEYS.apple).toEqual({
      clientId: 'APPLE_CLIENT_ID',
      clientSecret: 'APPLE_PRIVATE_KEY',
    });
    expect(PROVIDER_EXTRA_FIELDS.apple.map((field) => field.envKey)).toEqual([
      'APPLE_TEAM_ID',
      'APPLE_KEY_ID',
    ]);
    // The private key is never a plain extra: extras are returned in the clear.
    for (const fields of Object.values(PROVIDER_EXTRA_FIELDS)) {
      expect(fields.map((field) => field.envKey)).not.toContain('APPLE_PRIVATE_KEY');
    }
  });

  test('the admin card names Apple’s credentials as Apple does', () => {
    expect(providerCredentialLabels('apple')).toEqual({
      clientId: 'Services ID',
      clientSecret: 'Private key (.p8)',
      secretPlaceholder: 'Paste the whole .p8 file',
    });
    expect(providerCredentialLabels('github')).toEqual({
      clientId: 'Client ID',
      clientSecret: 'Client secret',
      secretPlaceholder: 'Enter client secret',
    });
  });

  test('apple has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('apple')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('apple')).toBe('Apple');
    expect(providerTagline('apple')).toBe('Apple Account sign-in');
    expect(PAT_PROVIDERS.has('apple')).toBe(false);
  });
});
