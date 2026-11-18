/**
 * Patreon provider smoke tests (OLO-9.47, #5060).
 *
 * Pins the slug on the linkable and auto-link trust sets: the Patreon identity resource carries
 * `is_email_verified`, which the normalizer maps to `email_verified`, so Patreon is `trusted` under
 * the OLO-9.16 trust-gate rule (#5029). Also pins the credential env keys and the display tables,
 * so a regression that drops Patreon from any of them fails loudly. Endpoint and verified-email
 * behaviour live in `better-auth-oauth-providers.test.ts`.
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

describe('Patreon provider (OLO-9.47)', () => {
  test('patreon is trusted (not provisional): linkable and auto-link trusted', () => {
    expect(providerTrustClass('patreon')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.patreon.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('patreon')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('patreon')).toBe(true);
  });

  test('admin-saved credentials overlay the Patreon env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.patreon).toEqual({
      clientId: 'PATREON_CLIENT_ID',
      clientSecret: 'PATREON_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.patreon).toBeUndefined();
  });

  test('patreon has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('patreon')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('patreon')).toBe('Patreon');
    expect(providerTagline('patreon')).toBe('Patreon account sign-in');
    expect(PAT_PROVIDERS.has('patreon')).toBe(false);
  });
});
