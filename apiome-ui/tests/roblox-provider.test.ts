/**
 * Roblox provider smoke tests (OLO-9.37, #5050).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: Apiome asks Roblox for
 * profile claims only, so there is no email claim — `link-only` under the OLO-9.16 trust-gate rule
 * (#5029) — and Roblox can never auto-link or create an account. Also pins the credential env keys
 * and the display tables, so a regression that drops Roblox from any of them fails loudly.
 * Discovery, scopes and no-email behaviour live in `better-auth-oauth-providers.test.ts`.
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

describe('Roblox provider (OLO-9.37)', () => {
  test('roblox is link-only: linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('roblox')).toBe('link-only');
    expect(PROVIDER_TRUST_CLASSES.roblox.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('roblox')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('roblox')).toBe(true);
  });

  test('admin-saved credentials overlay the Roblox client ID and secret env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.roblox).toEqual({
      clientId: 'ROBLOX_CLIENT_ID',
      clientSecret: 'ROBLOX_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.roblox).toBeUndefined();
  });

  test('roblox has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('roblox')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('roblox')).toBe('Roblox');
    expect(providerTagline('roblox')).toBe('Roblox account sign-in');
    expect(PAT_PROVIDERS.has('roblox')).toBe(false);
  });
});
