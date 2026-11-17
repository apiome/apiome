/**
 * HubSpot provider smoke tests (OLO-9.29, #5042).
 *
 * Pins the slug on the linkable set and **off** the auto-link trust set: HubSpot's token-info
 * resource returns the authorizing user's email with no verified claim, so it is `link-first`
 * under the OLO-9.16 trust-gate rule (#5029) and its email must never auto-link or create an
 * account. Also pins the credential env keys and the display tables, so a regression that drops
 * HubSpot from any of them fails loudly. Endpoint + fail-closed email behaviour live in
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

describe('HubSpot provider (OLO-9.29)', () => {
  test('hubspot is link-first: linkable, but never auto-link trusted', () => {
    expect(providerTrustClass('hubspot')).toBe('link-first');
    expect(PROVIDER_TRUST_CLASSES.hubspot.provisional).toBeUndefined();
    expect(PROVIDER_TRUST_CLASSES.hubspot.evidence).toBe('Token-info email, no verified claim');
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('hubspot')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('hubspot')).toBe(true);
  });

  test('admin-saved credentials overlay the HubSpot env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.hubspot).toEqual({
      clientId: 'HUBSPOT_CLIENT_ID',
      clientSecret: 'HUBSPOT_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.hubspot).toBeUndefined();
  });

  test('hubspot has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('hubspot')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('hubspot')).toBe('HubSpot');
    expect(providerTagline('hubspot')).toBe('HubSpot account sign-in');
    expect(PAT_PROVIDERS.has('hubspot')).toBe(false);
  });
});
