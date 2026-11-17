/**
 * Vercel provider smoke tests (OLO-9.27, #5040).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops Vercel from any of them fails loudly. Vercel was a
 * provisional `link-first` provider until its email semantics were confirmed; it is now `trusted`
 * under the OLO-9.16 trust-gate rule (#5029): Sign in with Vercel's userinfo resource reports
 * `email_verified`. Endpoint + verified / unverified email behaviour live in
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

describe('Vercel provider (OLO-9.27)', () => {
  test('vercel is trusted (no longer provisional), so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('vercel')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.vercel.provisional).toBeUndefined();
    expect(PROVIDER_TRUST_CLASSES.vercel.evidence).toBe('`email_verified` on `/login/oauth/userinfo`');
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('vercel')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('vercel')).toBe(true);
  });

  test('admin-saved credentials overlay the Vercel env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.vercel).toEqual({
      clientId: 'VERCEL_CLIENT_ID',
      clientSecret: 'VERCEL_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.vercel).toBeUndefined();
  });

  test('vercel has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('vercel')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('vercel')).toBe('Vercel');
    expect(providerTagline('vercel')).toBe('Vercel account sign-in');
    expect(PAT_PROVIDERS.has('vercel')).toBe(false);
  });
});
