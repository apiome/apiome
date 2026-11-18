/**
 * Gumroad provider smoke tests (OLO-9.48, #5061).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: Gumroad's `/v2/user`
 * returns the user's email with no verified claim, so Gumroad is `link-first` under the OLO-9.16
 * trust-gate rule (#5029) and its email must never auto-link or create an account. Also pins the
 * credential env keys and the display tables, so a regression that drops Gumroad from any of them
 * fails loudly. Endpoint and fail-closed email behaviour live in
 * `better-auth-oauth-providers.test.ts`.
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

describe('Gumroad provider (OLO-9.48)', () => {
  test('gumroad is link-first (not provisional): linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('gumroad')).toBe('link-first');
    expect(PROVIDER_TRUST_CLASSES.gumroad.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('gumroad')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('gumroad')).toBe(true);
  });

  test('admin-saved credentials overlay the Gumroad env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.gumroad).toEqual({
      clientId: 'GUMROAD_CLIENT_ID',
      clientSecret: 'GUMROAD_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.gumroad).toBeUndefined();
  });

  test('gumroad has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('gumroad')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('gumroad')).toBe('Gumroad');
    expect(providerTagline('gumroad')).toBe('Gumroad account sign-in');
    expect(PAT_PROVIDERS.has('gumroad')).toBe(false);
  });
});
