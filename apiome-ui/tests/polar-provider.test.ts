/**
 * Polar provider smoke tests (OLO-9.46, #5059).
 *
 * Pins the slug on the linkable and auto-link trust sets: Polar's OAuth userinfo carries a native
 * `email_verified` claim, so Polar is `trusted` under the OLO-9.16 trust-gate rule (#5029) —
 * decided at implementation, no longer provisional. Also pins the credential env keys and the
 * display tables, so a regression that drops Polar from any of them fails loudly. Endpoint and
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

describe('Polar provider (OLO-9.46)', () => {
  test('polar is trusted (no longer provisional): linkable and auto-link trusted', () => {
    expect(providerTrustClass('polar')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.polar.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('polar')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('polar')).toBe(true);
  });

  test('admin-saved credentials overlay the Polar env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.polar).toEqual({
      clientId: 'POLAR_CLIENT_ID',
      clientSecret: 'POLAR_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.polar).toBeUndefined();
  });

  test('polar has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('polar')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('polar')).toBe('Polar');
    expect(providerTagline('polar')).toBe('Polar account sign-in');
    expect(PAT_PROVIDERS.has('polar')).toBe(false);
  });
});
