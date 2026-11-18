/**
 * Twitch provider smoke tests (OLO-9.35, #5048).
 *
 * Pins the slug on both the linkable set and the auto-link trust set: Twitch's id token carries a
 * native `email_verified` claim with the `user:read:email` scope, so Twitch is `trusted` under the
 * OLO-9.16 trust-gate rule (#5029) and a verified address may auto-link or start a sign-up. Also
 * pins the credential env keys and the display tables, so a regression that drops Twitch from any
 * of them fails loudly. Endpoint and verified-email behaviour live in
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

describe('Twitch provider (OLO-9.35)', () => {
  test('twitch is trusted: linkable and auto-link trusted', () => {
    expect(providerTrustClass('twitch')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.twitch.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('twitch')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('twitch')).toBe(true);
  });

  test('admin-saved credentials overlay the Twitch env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.twitch).toEqual({
      clientId: 'TWITCH_CLIENT_ID',
      clientSecret: 'TWITCH_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.twitch).toBeUndefined();
  });

  test('twitch has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('twitch')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('twitch')).toBe('Twitch');
    expect(providerTagline('twitch')).toBe('Twitch account sign-in');
    expect(PAT_PROVIDERS.has('twitch')).toBe(false);
  });
});
