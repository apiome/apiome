/**
 * Paybin provider smoke tests (OLO-9.49, #5062).
 *
 * Pins the slug on the linkable and auto-link trust sets: the Paybin id token carries the standard
 * OIDC `email_verified` claim, so Paybin is `trusted` under the OLO-9.16 trust-gate rule (#5029) —
 * its earlier provisional link-first class is resolved. Also pins the credential env keys and the
 * display tables, so a regression that drops Paybin from any of them fails loudly. Endpoint and
 * verified-email behaviour live in `better-auth-oauth-providers.test.ts`.
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

describe('Paybin provider (OLO-9.49)', () => {
  test('paybin is trusted (no longer provisional): linkable and auto-link trusted', () => {
    expect(providerTrustClass('paybin')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.paybin.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('paybin')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('paybin')).toBe(true);
  });

  test('admin-saved credentials overlay the Paybin env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.paybin).toEqual({
      clientId: 'PAYBIN_CLIENT_ID',
      clientSecret: 'PAYBIN_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.paybin).toBeUndefined();
  });

  test('paybin has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('paybin')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('paybin')).toBe('Paybin');
    expect(providerTagline('paybin')).toBe('Paybin account sign-in');
    expect(PAT_PROVIDERS.has('paybin')).toBe(false);
  });
});
