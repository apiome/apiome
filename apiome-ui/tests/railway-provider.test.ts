/**
 * Railway provider smoke tests (OLO-9.28, #5041).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: Login with Railway's
 * `/oauth/me` returns an email with no documented verified claim, so it is `link-first` under the
 * OLO-9.16 trust-gate rule (#5029) and its email must never auto-link or create an account. Railway
 * was a provisional `link-first` default until its semantics were confirmed; the class is now
 * recorded as decided. Also pins the credential env keys and the display tables, so a regression
 * that drops Railway from any of them fails loudly. Endpoint + fail-closed email behaviour live in
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

describe('Railway provider (OLO-9.28)', () => {
  test('railway is link-first (no longer provisional): linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('railway')).toBe('link-first');
    expect(PROVIDER_TRUST_CLASSES.railway.provisional).toBeUndefined();
    expect(PROVIDER_TRUST_CLASSES.railway.evidence).toBe(
      '`/oauth/me` email, no documented verified claim'
    );
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('railway')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('railway')).toBe(true);
  });

  test('admin-saved credentials overlay the Railway env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.railway).toEqual({
      clientId: 'RAILWAY_CLIENT_ID',
      clientSecret: 'RAILWAY_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.railway).toBeUndefined();
  });

  test('railway has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('railway')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('railway')).toBe('Railway');
    expect(providerTagline('railway')).toBe('Railway account sign-in');
    expect(PAT_PROVIDERS.has('railway')).toBe(false);
  });
});
