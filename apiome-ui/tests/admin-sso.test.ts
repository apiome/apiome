/**
 * The admin console's SSO section — helpers and the server-side proxy (EID-1.1, #5011).
 *
 * Pinned: the values an IdP admin copies are the routes the plugin serves; the create payload
 * carries only what the chosen protocol needs; REST's stable `{error, message}` reaches the admin;
 * and the proxy forwards only the method/path shapes the REST surface defines, presenting the admin
 * session upstream and clearing the routable-provider cache after a write.
 */

jest.mock('@lib/rest-auth', () => ({ REST_API_BASE_URL: 'http://rest.test/v1' }));

import { describe, expect, test } from '@jest/globals';

import {
  buildSsoCreatePayload,
  EMPTY_SSO_DRAFT,
  ssoAdminErrorMessage,
  ssoSetupDetails,
  suggestSsoSlug,
} from '../lib/auth/admin-sso';
import { proxySsoAdmin, ssoAdminUpstreamPath } from '../lib/auth/admin-sso-proxy';
import * as resolver from '../lib/auth/sso-provider-resolver';

const ID = '3f2b8c1e-0d4a-4b7e-9c11-2a6f5e8d9b01';

describe('suggestSsoSlug', () => {
  test.each([
    ['Acme Okta', 'acme-okta'],
    ['  Acme — Entra ID (EU) ', 'acme-entra-id-eu'],
    ['Ünïcödé Corp', 'unicode-corp'],
    ['x'.repeat(40), 'x'.repeat(28)],
    ['!!!', ''],
  ])('%s → %s', (name, slug) => {
    expect(suggestSsoSlug(name)).toBe(slug);
  });
});

describe('ssoSetupDetails', () => {
  test('OIDC: the redirect URI', () => {
    expect(ssoSetupDetails('https://app.test/', { protocol: 'oidc', plugin_provider_id: 'sso-acme' })).toEqual([
      { label: 'Redirect URI', value: 'https://app.test/api/auth/sso/callback/sso-acme' },
    ]);
  });

  test('SAML: the ACS URL, and the SP metadata URL as entity id', () => {
    const details = ssoSetupDetails('https://app.test', { protocol: 'saml', plugin_provider_id: 'sso-acme' });
    expect(details.map((d) => d.value)).toEqual([
      'https://app.test/api/auth/sso/saml2/sp/acs/sso-acme',
      'https://app.test/api/auth/sso/saml2/sp/metadata?providerId=sso-acme',
      'https://app.test/api/auth/sso/saml2/sp/metadata?providerId=sso-acme',
    ]);
  });
});

describe('buildSsoCreatePayload', () => {
  test('OIDC sends the issuer, client id and secret — nothing SAML', () => {
    const payload = buildSsoCreatePayload({
      ...EMPTY_SSO_DRAFT,
      displayName: ' Acme ',
      slug: 'acme',
      issuer: ' https://idp.test ',
      clientId: 'apiome',
      clientSecret: 's3cret',
      metadataXml: '<x/>',
    });
    expect(payload).toEqual({
      protocol: 'oidc',
      slug: 'acme',
      display_name: 'Acme',
      issuer: 'https://idp.test',
      client_id: 'apiome',
      client_secret: 's3cret',
    });
  });

  test('SAML prefers pasted XML over a URL, and sends the attribute only when chosen', () => {
    const base = { ...EMPTY_SSO_DRAFT, protocol: 'saml' as const, displayName: 'Acme', slug: 'acme', tenantId: ' t-1 ' };
    expect(buildSsoCreatePayload({ ...base, metadataUrl: 'https://idp.test/md' })).toEqual({
      protocol: 'saml',
      slug: 'acme',
      display_name: 'Acme',
      tenant_id: 't-1',
      metadata_url: 'https://idp.test/md',
      email_source: 'nameid',
    });
    expect(
      buildSsoCreatePayload({ ...base, metadataXml: '<md/>', metadataUrl: 'https://ignored', emailSource: 'attribute', emailAttribute: ' mail ', spPrivateKey: 'PEM' })
    ).toEqual(expect.objectContaining({ metadata_xml: '<md/>', email_attribute: 'mail', sp_private_key: 'PEM' }));
  });
});

describe('ssoAdminErrorMessage', () => {
  test('relays REST’s stable message', () => {
    expect(ssoAdminErrorMessage(422, { detail: { error: 'sso-domain-claimed', message: 'acme.com is taken.' } }, 'x')).toBe('acme.com is taken.');
  });
  test('names an expired session', () => {
    expect(ssoAdminErrorMessage(401, {}, 'x')).toMatch(/session has expired/);
  });
  test('falls back', () => {
    expect(ssoAdminErrorMessage(502, null, 'fallback')).toBe('fallback');
  });
});

describe('ssoAdminUpstreamPath — only the REST surface’s own routes', () => {
  test.each([
    ['GET', [], '/sso/providers'],
    ['POST', [], '/sso/providers'],
    ['GET', [ID], `/sso/providers/${ID}`],
    ['PATCH', [ID], `/sso/providers/${ID}`],
    ['DELETE', [ID], `/sso/providers/${ID}`],
    ['POST', [ID, 'domains'], `/sso/providers/${ID}/domains`],
    ['DELETE', [ID, 'domains', 'acme.com'], `/sso/providers/${ID}/domains/acme.com`],
    ['POST', [ID, 'domains', 'Acme.com', 'verify'], `/sso/providers/${ID}/domains/acme.com/verify`],
  ])('%s %j → %s', (method, segments, path) => {
    expect(ssoAdminUpstreamPath(method, segments)).toBe(path);
  });

  test.each([
    ['PUT', []],
    ['DELETE', []],
    ['GET', ['not-a-uuid']],
    ['GET', [ID, 'domains']],
    ['POST', [ID, 'domains', '../../auth-providers']],
    ['POST', [ID, 'domains', 'acme.com', 'unverify']],
    ['GET', ['..', 'auth-providers']],
  ])('refuses %s %j', (method, segments) => {
    expect(ssoAdminUpstreamPath(method, segments)).toBeNull();
  });
});

describe('proxySsoAdmin', () => {
  test('forwards with the admin session and clears the routable-provider cache after a write', async () => {
    const invalidate = jest.spyOn(resolver, 'invalidateSsoProviderCache');
    const fetchImpl = jest.fn(async () => ({ status: 201, json: async () => ({ id: ID }) }) as unknown as Response);
    const result = await proxySsoAdmin('admin-token', 'POST', [ID, 'domains'], { domain: 'acme.com' }, fetchImpl as unknown as typeof fetch);
    expect(result).toEqual({ status: 201, body: { id: ID } });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`http://rest.test/v1/admin/sso/providers/${ID}/domains`);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-Admin-Session']).toBe('admin-token');
    expect(init.body).toBe(JSON.stringify({ domain: 'acme.com' }));
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  test('a read does not clear the cache', async () => {
    const invalidate = jest.spyOn(resolver, 'invalidateSsoProviderCache').mockClear();
    const fetchImpl = jest.fn(async () => ({ status: 200, json: async () => ({ providers: [] }) }) as unknown as Response);
    await proxySsoAdmin('t', 'GET', [], undefined, fetchImpl as unknown as typeof fetch);
    expect(invalidate).not.toHaveBeenCalled();
  });

  test('an undefined route is refused locally and never reaches REST', async () => {
    const fetchImpl = jest.fn();
    const result = await proxySsoAdmin('t', 'GET', ['..', 'auth-providers'], undefined, fetchImpl as unknown as typeof fetch);
    expect(result.status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
