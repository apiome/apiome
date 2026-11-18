/**
 * PayPal environment helpers (OLO-9.45, #5058).
 *
 * Pins how `PAYPAL_ENVIRONMENT` is read — optional, trimmed, case-insensitive, fail-safe to live —
 * and the discovery and userinfo hosts each environment selects.
 */

import {
  DEFAULT_PAYPAL_ENVIRONMENT,
  PAYPAL_PROVIDER_ID,
  paypalDiscoveryUrl,
  paypalEnvironment,
  paypalUserInfoUrl,
} from '../lib/auth/paypal-environment';

describe('paypalEnvironment', () => {
  test('the slug and the default are fixed', () => {
    expect(PAYPAL_PROVIDER_ID).toBe('paypal');
    expect(DEFAULT_PAYPAL_ENVIRONMENT).toBe('live');
  });

  test.each([
    ['unset', undefined, 'live'],
    ['blank', '   ', 'live'],
    ['live', 'live', 'live'],
    ['sandbox', 'sandbox', 'sandbox'],
    ['sandbox with whitespace and capitals', '  SANDBOX ', 'sandbox'],
    ['an unknown value', 'production', 'live'],
    ['a near miss', 'sandbx', 'live'],
  ])('%s → %s', (_label, value, expected) => {
    expect(paypalEnvironment({ PAYPAL_ENVIRONMENT: value })).toBe(expected);
  });
});

describe('PayPal hosts per environment', () => {
  test('live uses www.paypal.com discovery and the api-m userinfo', () => {
    expect(paypalDiscoveryUrl({})).toBe('https://www.paypal.com/.well-known/openid-configuration');
    expect(paypalUserInfoUrl({})).toBe(
      'https://api-m.paypal.com/v1/identity/oauth2/userinfo?schema=paypalv1.1'
    );
  });

  test('sandbox uses the sandbox discovery and userinfo hosts', () => {
    const env = { PAYPAL_ENVIRONMENT: 'sandbox' };
    expect(paypalDiscoveryUrl(env)).toBe(
      'https://www.sandbox.paypal.com/.well-known/openid-configuration'
    );
    expect(paypalUserInfoUrl(env)).toBe(
      'https://api-m.sandbox.paypal.com/v1/identity/oauth2/userinfo?schema=paypalv1.1'
    );
  });
});
