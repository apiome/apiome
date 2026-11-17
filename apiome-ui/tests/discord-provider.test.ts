/**
 * Discord provider smoke tests (OLO-9.19, #5032).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops Discord from any of them fails loudly. Endpoint + verified-email
 * behaviour live in `better-auth-oauth-providers.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';
import { PROVIDER_CRED_ENV_KEYS } from '../lib/auth/provider-config-resolver';
import { providerTrustClass } from '../lib/auth/provider-trust-classes';
import {
  PAT_PROVIDERS,
  providerTagline,
} from '../src/app/components/ade/account/linkedAccountsModel';
import { getProviderBrand } from '../src/app/components/auth/provider-brand';

describe('Discord provider (OLO-9.19)', () => {
  test('discord is trusted, so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('discord')).toBe('trusted');
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('discord')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('discord')).toBe(true);
  });

  test('admin-saved credentials overlay the Discord env vars', () => {
    expect(PROVIDER_CRED_ENV_KEYS.discord).toEqual({
      clientId: 'DISCORD_CLIENT_ID',
      clientSecret: 'DISCORD_CLIENT_SECRET',
    });
  });

  test('discord has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('discord')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('discord')).toBe('Discord account sign-in');
    expect(PAT_PROVIDERS.has('discord')).toBe(false);
  });
});
