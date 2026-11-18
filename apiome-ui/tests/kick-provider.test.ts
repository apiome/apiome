/**
 * Kick provider smoke tests (OLO-9.38, #5051).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: Kick's
 * `/public/v1/users` returns an email with no verified claim, so Kick is `link-first` under the
 * OLO-9.16 trust-gate rule (#5029) — confirmed at implementation, no longer provisional — and its
 * email must never auto-link or create an account. Also pins the credential env keys and the
 * display tables, so a regression that drops Kick from any of them fails loudly. Endpoint and
 * fail-closed email behaviour live in `better-auth-oauth-providers.test.ts`.
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

describe('Kick provider (OLO-9.38)', () => {
  test('kick is link-first (no longer provisional): linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('kick')).toBe('link-first');
    expect(PROVIDER_TRUST_CLASSES.kick.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('kick')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('kick')).toBe(true);
  });

  test('admin-saved credentials overlay the Kick env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.kick).toEqual({
      clientId: 'KICK_CLIENT_ID',
      clientSecret: 'KICK_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.kick).toBeUndefined();
  });

  test('kick has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('kick')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('kick')).toBe('Kick');
    expect(providerTagline('kick')).toBe('Kick account sign-in');
    expect(PAT_PROVIDERS.has('kick')).toBe(false);
  });
});
