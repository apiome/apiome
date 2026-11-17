/**
 * Atlassian provider smoke tests (OLO-9.8, #4991).
 *
 * Pins the slug on the linkable / auto-link sets and on the display tables, so a regression that
 * drops Atlassian from any of them fails loudly. Endpoint + verified-email behaviour live in
 * `better-auth-oauth-providers.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';
import { PROVIDER_CRED_ENV_KEYS } from '../lib/auth/provider-config-resolver';
import { providerTagline } from '../src/app/components/ade/account/linkedAccountsModel';
import { getProviderBrand } from '../src/app/components/auth/provider-brand';

describe('Atlassian provider (OLO-9.8)', () => {
  test('atlassian is on the auto-link trust and linkable sets', () => {
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('atlassian')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('atlassian')).toBe(true);
  });

  test('admin-saved credentials overlay the Atlassian env vars', () => {
    expect(PROVIDER_CRED_ENV_KEYS.atlassian).toEqual({
      clientId: 'ATLASSIAN_CLIENT_ID',
      clientSecret: 'ATLASSIAN_CLIENT_SECRET',
    });
  });

  test('atlassian has its own brand icon and tagline', () => {
    expect(getProviderBrand('atlassian')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('atlassian')).toBe('Atlassian account for Jira and Confluence teams');
  });
});
