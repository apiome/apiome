/**
 * Notion provider smoke tests (OLO-9.21, #5034).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: Notion returns the owner
 * user's email with no verified claim, so it is `link-first` under the OLO-9.16 trust-gate rule
 * (#5029) and its email must never auto-link or create an account. Also pins the credential env
 * keys and the display tables, so a regression that drops Notion from any of them fails loudly.
 * Endpoint + fail-closed email behaviour live in `better-auth-oauth-providers.test.ts`.
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

describe('Notion provider (OLO-9.21)', () => {
  test('notion is link-first: linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('notion')).toBe('link-first');
    expect(PROVIDER_TRUST_CLASSES.notion.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('notion')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('notion')).toBe(true);
  });

  test('admin-saved credentials overlay the Notion env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.notion).toEqual({
      clientId: 'NOTION_CLIENT_ID',
      clientSecret: 'NOTION_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.notion).toBeUndefined();
  });

  test('notion has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('notion')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('notion')).toBe('Notion account sign-in');
    expect(PAT_PROVIDERS.has('notion')).toBe(false);
  });
});
