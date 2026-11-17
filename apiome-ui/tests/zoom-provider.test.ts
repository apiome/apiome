/**
 * Zoom provider smoke tests (OLO-9.25, #5038).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops Zoom from any of them fails loudly. Zoom is `trusted`
 * under the OLO-9.16 trust-gate rule (#5029): `/v2/users/me` reports `verified`.
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

describe('Zoom provider (OLO-9.25)', () => {
  test('zoom is trusted, so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('zoom')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.zoom.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('zoom')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('zoom')).toBe(true);
  });

  test('admin-saved credentials overlay the Zoom env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.zoom).toEqual({
      clientId: 'ZOOM_CLIENT_ID',
      clientSecret: 'ZOOM_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.zoom).toBeUndefined();
  });

  test('zoom has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('zoom')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('zoom')).toBe('Zoom account sign-in');
    expect(PAT_PROVIDERS.has('zoom')).toBe(false);
  });
});
