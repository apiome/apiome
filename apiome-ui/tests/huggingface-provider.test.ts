/**
 * Hugging Face provider smoke tests (OLO-9.26, #5039).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops Hugging Face from any of them fails loudly. Hugging Face is
 * `trusted` under the OLO-9.16 trust-gate rule (#5029): its userinfo resource reports
 * `email_verified`. Discovery + verified / unverified email behaviour live in
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

describe('Hugging Face provider (OLO-9.26)', () => {
  test('huggingface is trusted, so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('huggingface')).toBe('trusted');
    expect(PROVIDER_TRUST_CLASSES.huggingface.provisional).toBeUndefined();
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('huggingface')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('huggingface')).toBe(true);
  });

  test('admin-saved credentials overlay the Hugging Face env vars; there is no extra setting', () => {
    expect(PROVIDER_CRED_ENV_KEYS.huggingface).toEqual({
      clientId: 'HUGGINGFACE_CLIENT_ID',
      clientSecret: 'HUGGINGFACE_CLIENT_SECRET',
    });
    expect(PROVIDER_EXTRA_FIELDS.huggingface).toBeUndefined();
  });

  test('huggingface has its own brand icon, label and tagline, and stores no access token', () => {
    expect(getProviderBrand('huggingface')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerLabel('huggingface')).toBe('Hugging Face');
    expect(providerTagline('huggingface')).toBe('Hugging Face account sign-in');
    expect(PAT_PROVIDERS.has('huggingface')).toBe(false);
  });
});
