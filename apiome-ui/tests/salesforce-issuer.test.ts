/**
 * Salesforce issuer helper tests (OLO-9.20, #5033) for `lib/auth/salesforce-issuer.ts`.
 *
 * Pins the engine-neutral Salesforce facts: provider slug, the optional issuer base URL (default
 * login.salesforce.com; trimmed, blank counts as unset, trailing slash stripped — the way
 * `OKTA_ISSUER` is read) and the userinfo resource derived from it.
 */
import { describe, test, expect } from '@jest/globals';

import {
  DEFAULT_SALESFORCE_ISSUER_BASE_URL,
  SALESFORCE_PROVIDER_ID,
  salesforceIssuerBaseUrl,
  salesforceUserInfoUrl,
} from '../lib/auth/salesforce-issuer';

describe('salesforce issuer env contract', () => {
  test('provider id is the stable slug salesforce', () => {
    expect(SALESFORCE_PROVIDER_ID).toBe('salesforce');
  });

  test('unset / blank issuer falls back to login.salesforce.com', () => {
    expect(DEFAULT_SALESFORCE_ISSUER_BASE_URL).toBe('https://login.salesforce.com');
    expect(salesforceIssuerBaseUrl({})).toBe('https://login.salesforce.com');
    expect(salesforceIssuerBaseUrl({ SALESFORCE_ISSUER: '   ' })).toBe(
      'https://login.salesforce.com'
    );
  });

  test('SALESFORCE_ISSUER is trimmed and its trailing slash stripped', () => {
    expect(salesforceIssuerBaseUrl({ SALESFORCE_ISSUER: 'https://acme.my.salesforce.com/' })).toBe(
      'https://acme.my.salesforce.com'
    );
    expect(salesforceIssuerBaseUrl({ SALESFORCE_ISSUER: '  https://test.salesforce.com  ' })).toBe(
      'https://test.salesforce.com'
    );
    expect(salesforceIssuerBaseUrl({ SALESFORCE_ISSUER: 'http://localhost:9006/salesforce' })).toBe(
      'http://localhost:9006/salesforce'
    );
  });

  test('the userinfo resource sits under the configured issuer', () => {
    expect(salesforceUserInfoUrl({})).toBe(
      'https://login.salesforce.com/services/oauth2/userinfo'
    );
    expect(salesforceUserInfoUrl({ SALESFORCE_ISSUER: 'https://acme.my.salesforce.com/' })).toBe(
      'https://acme.my.salesforce.com/services/oauth2/userinfo'
    );
  });
});
