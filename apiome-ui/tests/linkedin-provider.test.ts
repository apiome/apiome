/**
 * LinkedIn provider smoke tests (OLO-9.18, #5031).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops LinkedIn from any of them fails loudly. Discovery + verified-email
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

describe('LinkedIn provider (OLO-9.18)', () => {
  test('linkedin is trusted, so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('linkedin')).toBe('trusted');
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('linkedin')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('linkedin')).toBe(true);
  });

  test('admin-saved credentials overlay the LinkedIn env vars', () => {
    expect(PROVIDER_CRED_ENV_KEYS.linkedin).toEqual({
      clientId: 'LINKEDIN_CLIENT_ID',
      clientSecret: 'LINKEDIN_CLIENT_SECRET',
    });
  });

  test('linkedin has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('linkedin')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('linkedin')).toBe('LinkedIn professional account sign-in');
    expect(PAT_PROVIDERS.has('linkedin')).toBe(false);
  });
});
