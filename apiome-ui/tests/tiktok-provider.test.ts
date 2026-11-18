/**
 * TikTok provider smoke tests (OLO-9.36, #5049).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: TikTok's user info exposes
 * no email address, so it is `link-only` under the OLO-9.16 trust-gate rule (#5029) and can never
 * auto-link or create an account. Also pins the credential env keys — TikTok calls the client ID a
 * "client key", so the env var is `TIKTOK_CLIENT_KEY` — and the display tables, so a regression
 * that drops TikTok from any of them fails loudly. Endpoint, `client_key` exchange and no-email
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

describe('TikTok provider (OLO-9.36)', () => {
  test('tiktok is link-only: linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('tiktok')).toBe('link-only');
    expect(PROVIDER_TRUST_CLASSES.tiktok.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('tiktok')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('tiktok')).toBe(true);
  });

  test('admin-saved credentials overlay the TikTok client key and secret env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.tiktok).toEqual({
      clientId: 'TIKTOK_CLIENT_KEY',
      clientSecret: 'TIKTOK_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.tiktok).toBeUndefined();
  });

  test('tiktok has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('tiktok')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('tiktok')).toBe('TikTok');
    expect(providerTagline('tiktok')).toBe('TikTok account sign-in');
    expect(PAT_PROVIDERS.has('tiktok')).toBe(false);
  });
});
