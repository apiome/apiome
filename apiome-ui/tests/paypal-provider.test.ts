/**
 * PayPal provider smoke tests (OLO-9.45, #5058).
 *
 * Pins the slug on the linkable / auto-link sets, on its recorded trust class and on the display
 * tables, so a regression that drops PayPal from any of them fails loudly. Discovery, the
 * environment extra and verified-email behaviour live in `better-auth-oauth-providers.test.ts`
 * and `paypal-environment.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';
import { PROVIDER_EXTRA_FIELDS } from '../lib/auth/admin-provider-config';
import { paypalEnvironment } from '../lib/auth/paypal-environment';
import { PROVIDER_CRED_ENV_KEYS, applyResolvedOverlay } from '../lib/auth/provider-config-resolver';
import { getProviderDescriptor } from '../lib/auth/provider-registry';
import { providerTrustClass } from '../lib/auth/provider-trust-classes';
import {
  PAT_PROVIDERS,
  providerTagline,
} from '../src/app/components/ade/account/linkedAccountsModel';
import { getProviderBrand } from '../src/app/components/auth/provider-brand';

describe('PayPal provider (OLO-9.45)', () => {
  test('paypal is trusted, so it is on the auto-link trust and linkable sets', () => {
    expect(providerTrustClass('paypal')).toBe('trusted');
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('paypal')).toBe(true);
    expect(LINKABLE_PROVIDERS.has('paypal')).toBe(true);
  });

  test('admin-saved credentials overlay the PayPal env vars', () => {
    expect(PROVIDER_CRED_ENV_KEYS.paypal).toEqual({
      clientId: 'PAYPAL_CLIENT_ID',
      clientSecret: 'PAYPAL_CLIENT_SECRET',
    });
  });

  test('the environment is an optional extra: offered on the admin card, never required', () => {
    expect(PROVIDER_EXTRA_FIELDS.paypal).toEqual([
      expect.objectContaining({
        envKey: 'PAYPAL_ENVIRONMENT',
        label: 'Environment',
        defaultValue: 'live',
      }),
    ]);
    expect(getProviderDescriptor('paypal')?.requiredFields.map((f) => f.field)).toEqual([
      'client_id',
      'client_secret',
    ]);
  });

  test('an admin-saved environment wins over env; a blank one keeps the env value', () => {
    const base = { PAYPAL_ENVIRONMENT: 'live' };
    const stored = (environment: string) => ({
      providers: {
        paypal: {
          enabled: true,
          client_id: 'pp-id',
          client_secret: 'pp-secret',
          config: { PAYPAL_ENVIRONMENT: environment },
        },
      },
    });

    expect(paypalEnvironment(applyResolvedOverlay(base, stored('sandbox')))).toBe('sandbox');
    expect(
      paypalEnvironment(applyResolvedOverlay({ PAYPAL_ENVIRONMENT: 'sandbox' }, stored('   ')))
    ).toBe('sandbox');
  });

  test('paypal has its own brand icon and tagline, and stores no access token', () => {
    expect(getProviderBrand('paypal')).not.toBe(getProviderBrand('not-a-provider'));
    expect(providerTagline('paypal')).toBe('PayPal account sign-in');
    expect(PAT_PROVIDERS.has('paypal')).toBe(false);
  });
});
