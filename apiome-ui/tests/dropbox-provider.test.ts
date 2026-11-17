/**
 * Dropbox provider smoke tests (OLO-9.24, #5037).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops Dropbox from any of them fails loudly. Dropbox is `trusted`
 * under the OLO-9.16 trust-gate rule (#5029): `get_current_account` reports `email_verified`.
 * Endpoint + verified / unverified email behaviour live in `better-auth-oauth-providers.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';
import { PROVIDER_EXTRA_FIELDS } from '../lib/auth/admin-provider-config';
import { PROVIDER_CRED_ENV_KEYS } from '../lib/auth/provider-config-resolver';
import { PROVIDER_TRUST_CLASSES, providerTrustClass } from '../lib/auth/provider-trust-classes';
import {
  PAT_PROVIDERS,
  providerTagline,
} from '../src/app/components/ade/account/linkedAccountsModel';
import { getProviderBrand } from '../src/app/components/auth/provider-brand';

describe('Dropbox provider (OLO-9.24)', () => {
  test('dropbox is trusted, so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('dropbox')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.dropbox.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('dropbox')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('dropbox')).toBe(true);
  });

  test('admin-saved credentials overlay the Dropbox env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.dropbox).toEqual({
      clientId: 'DROPBOX_CLIENT_ID',
      clientSecret: 'DROPBOX_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.dropbox).toBeUndefined();
  });

  test('dropbox has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('dropbox')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('dropbox')).toBe('Dropbox account sign-in');
    expect(PAT_PROVIDERS.has('dropbox')).toBe(false);
  });
});
