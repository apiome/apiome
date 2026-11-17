/**
 * Slack provider smoke tests (OLO-9.17, #5030).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops Slack from any of them fails loudly. Discovery + verified-email
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

describe('Slack provider (OLO-9.17)', () => {
  test('slack is trusted, so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('slack')).toBe('trusted');
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('slack')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('slack')).toBe(true);
  });

  test('admin-saved credentials overlay the Slack env vars', () => {
    expect(PROVIDER_CRED_ENV_KEYS.slack).toEqual({
      clientId: 'SLACK_CLIENT_ID',
      clientSecret: 'SLACK_CLIENT_SECRET',
    });
  });

  test('slack has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('slack')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('slack')).toBe('Slack workspace account sign-in');
    expect(PAT_PROVIDERS.has('slack')).toBe(false);
  });
});
