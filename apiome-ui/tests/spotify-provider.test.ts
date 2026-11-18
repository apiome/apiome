/**
 * Spotify provider smoke tests (OLO-9.34, #5047).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: Spotify documents the
 * `/v1/me` email as unverified, so Spotify is `link-first` under the OLO-9.16 trust-gate rule
 * (#5029) and its email must never auto-link or create an account. Also pins the credential env
 * keys and the display tables, so a regression that drops Spotify from any of them fails loudly.
 * Endpoint and fail-closed email behaviour live in `better-auth-oauth-providers.test.ts`.
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

describe('Spotify provider (OLO-9.34)', () => {
  test('spotify is link-first: linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('spotify')).toBe('link-first');
    expect(PROVIDER_TRUST_CLASSES.spotify.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('spotify')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('spotify')).toBe(true);
  });

  test('admin-saved credentials overlay the Spotify env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.spotify).toEqual({
      clientId: 'SPOTIFY_CLIENT_ID',
      clientSecret: 'SPOTIFY_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.spotify).toBeUndefined();
  });

  test('spotify has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('spotify')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('spotify')).toBe('Spotify');
    expect(providerTagline('spotify')).toBe('Spotify account sign-in');
    expect(PAT_PROVIDERS.has('spotify')).toBe(false);
  });
});
