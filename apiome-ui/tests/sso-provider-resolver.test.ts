/**
 * The routable enterprise SSO providers and their `defaultSSO` mapping — EID-1.1 (#5011).
 *
 * `lib/auth/sso-provider-resolver.ts` reads enabled providers × verified domains from REST's
 * service-token-gated endpoint and hands them to Better Auth's SSO plugin. Pinned: no token, an
 * outage or a malformed payload all mean "no SSO" (never an exception, never a stale secret in a
 * log); one `defaultSSO` entry per verified domain, under the `sso-<slug>` id; OIDC carries its
 * discovered endpoints and secret; SAML carries the IdP certificate, our ACS and SP entity id, and
 * an email mapping that honours the provider's chosen email source.
 */

jest.mock('@lib/rest-auth', () => ({ REST_API_BASE_URL: 'http://rest.test/v1' }));

import { beforeEach, describe, expect, test } from '@jest/globals';

import {
  buildDefaultSsoEntries,
  findSsoProvider,
  invalidateSsoProviderCache,
  NO_SSO_PROVIDERS,
  parseResolvedProvider,
  pluginConfigFor,
  resolveSsoProviders,
  SAML_NAMEID_EMAIL_SENTINEL,
  samlSpEntityId,
} from '../lib/auth/sso-provider-resolver';

const BASE = 'https://app.example.test/api/auth';

const OIDC_ROW = {
  id: 'p1',
  slug: 'acme',
  plugin_provider_id: 'sso-acme',
  identity_kind: 'sso:acme',
  protocol: 'oidc',
  display_name: 'Acme',
  issuer: 'https://idp.acme.test',
  tenant_id: null,
  domains: ['acme.test', 'Acme.io'],
  oidc_config: {
    client_id: 'apiome',
    discovery_endpoint: 'https://idp.acme.test/.well-known/openid-configuration',
    authorization_endpoint: 'https://idp.acme.test/auth',
    token_endpoint: 'https://idp.acme.test/token',
    jwks_uri: 'https://idp.acme.test/certs',
    userinfo_endpoint: null,
    scopes: ['openid', 'email', 'profile'],
    pkce: true,
    token_endpoint_authentication: 'client_secret_post',
  },
  saml_config: null,
  client_secret: 'oidc-secret',
  sp_private_key: null,
};

const SAML_ROW = {
  id: 'p2',
  slug: 'acme-saml',
  protocol: 'saml',
  display_name: 'Acme SAML',
  issuer: 'https://idp.acme.test/saml',
  domains: ['saml.test'],
  oidc_config: null,
  saml_config: {
    idp_entity_id: 'https://idp.acme.test/saml',
    sso_url: 'https://idp.acme.test/saml/sso',
    sso_binding: 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect',
    certificates: ['MIIC-cert'],
    email_source: 'nameid',
    email_attribute: null,
  },
  client_secret: null,
  sp_private_key: null,
};

function response(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
}

beforeEach(() => {
  invalidateSsoProviderCache();
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});

describe('parseResolvedProvider', () => {
  test('maps the wire row, lower-casing domains', () => {
    const provider = parseResolvedProvider(OIDC_ROW)!;
    expect(provider.pluginProviderId).toBe('sso-acme');
    expect(provider.identityKind).toBe('sso:acme');
    expect(provider.domains).toEqual(['acme.test', 'acme.io']);
    expect(provider.clientSecret).toBe('oidc-secret');
  });

  test('derives the ids from the slug when the row omits them', () => {
    const provider = parseResolvedProvider(SAML_ROW)!;
    expect(provider.pluginProviderId).toBe('sso-acme-saml');
    expect(provider.identityKind).toBe('sso:acme-saml');
  });

  test.each([
    ['no domains', { ...OIDC_ROW, domains: [] }],
    ['an unknown protocol', { ...OIDC_ROW, protocol: 'ldap' }],
    ['no slug', { ...OIDC_ROW, slug: '' }],
    ['not an object', 'nope'],
  ])('drops a row with %s', (_label, row) => {
    expect(parseResolvedProvider(row)).toBeNull();
  });
});

describe('resolveSsoProviders', () => {
  test('is empty without a service token, and never calls REST', async () => {
    const fetchImpl = jest.fn();
    await expect(resolveSsoProviders({}, 1, fetchImpl as unknown as typeof fetch)).resolves.toBe(NO_SSO_PROVIDERS);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  test('reads the routable set with the token, and caches it', async () => {
    const fetchImpl = jest.fn(async () => response({ providers: [OIDC_ROW, SAML_ROW], fingerprint: 'fp-1' }));
    const env = { INTERNAL_SERVICE_TOKEN: 'svc', REST_API_BASE_URL: 'http://rest.internal/v1/' };
    const first = await resolveSsoProviders(env, 1_000, fetchImpl as unknown as typeof fetch);
    const second = await resolveSsoProviders(env, 2_000, fetchImpl as unknown as typeof fetch);
    expect(first.providers.map((p) => p.slug)).toEqual(['acme', 'acme-saml']);
    expect(first.fingerprint).toBe('fp-1');
    expect(second).toBe(first);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://rest.internal/v1/internal/sso/providers/resolved');
    expect((init.headers as Record<string, string>)['X-Internal-Service-Token']).toBe('svc');
  });

  test.each([
    ['an error status', async () => response({}, 503)],
    ['a network failure', async () => Promise.reject(new TypeError('fetch failed'))],
    ['a malformed body', async () => response({ providers: 'nope' })],
  ])('degrades to no SSO on %s', async (_label, impl) => {
    const resolved = await resolveSsoProviders({ INTERNAL_SERVICE_TOKEN: 'svc' }, 1, jest.fn(impl) as unknown as typeof fetch);
    expect(resolved.providers).toEqual([]);
  });

  test('never logs the body (it carries decrypted secrets)', async () => {
    const warn = jest.spyOn(console, 'warn');
    await resolveSsoProviders({ INTERNAL_SERVICE_TOKEN: 'svc' }, 1, jest.fn(async () => response({}, 500)) as unknown as typeof fetch);
    expect(JSON.stringify(warn.mock.calls)).not.toContain('oidc-secret');
  });
});

describe('the defaultSSO mapping', () => {
  const resolved = {
    providers: [parseResolvedProvider(OIDC_ROW)!, parseResolvedProvider(SAML_ROW)!],
    fingerprint: 'f',
  };

  test('one entry per verified domain, under the plugin id', () => {
    const entries = buildDefaultSsoEntries(resolved, BASE);
    expect(entries.map((e) => [e.domain, e.providerId])).toEqual([
      ['acme.test', 'sso-acme'],
      ['acme.io', 'sso-acme'],
      ['saml.test', 'sso-acme-saml'],
    ]);
  });

  test('OIDC carries the discovered endpoints and the secret', () => {
    const { oidcConfig } = pluginConfigFor(resolved.providers[0], BASE)!;
    expect(oidcConfig).toEqual(
      expect.objectContaining({
        issuer: 'https://idp.acme.test',
        clientId: 'apiome',
        clientSecret: 'oidc-secret',
        pkce: true,
        jwksEndpoint: 'https://idp.acme.test/certs',
        tokenEndpointAuthentication: 'client_secret_post',
      })
    );
  });

  test('SAML carries the IdP certificate, our ACS and SP entity id, and the NameID email source', () => {
    const { samlConfig } = pluginConfigFor(resolved.providers[1], BASE)!;
    expect(samlConfig).toEqual(
      expect.objectContaining({
        issuer: 'https://idp.acme.test/saml',
        entryPoint: 'https://idp.acme.test/saml/sso',
        cert: 'MIIC-cert',
        callbackUrl: `${BASE}/sso/saml2/sp/acs/sso-acme-saml`,
        wantAssertionsSigned: true,
        mapping: { email: SAML_NAMEID_EMAIL_SENTINEL },
      })
    );
    expect((samlConfig as { spMetadata: { entityID: string } }).spMetadata.entityID).toBe(samlSpEntityId(BASE, 'sso-acme-saml'));
    expect(samlConfig).not.toHaveProperty('privateKey');
  });

  test('SAML with an email attribute maps that attribute, and signs requests with an SP key', () => {
    const provider = parseResolvedProvider({
      ...SAML_ROW,
      saml_config: { ...SAML_ROW.saml_config, email_source: 'attribute', email_attribute: 'mail' },
      sp_private_key: 'PEM',
    })!;
    const { samlConfig } = pluginConfigFor(provider, BASE)!;
    expect((samlConfig as { mapping: { email: string } }).mapping.email).toBe('mail');
    expect(samlConfig).toEqual(expect.objectContaining({ privateKey: 'PEM', authnRequestsSigned: true }));
  });

  test('a provider whose stored config is unusable contributes no entry', () => {
    const noSecret = parseResolvedProvider({ ...OIDC_ROW, client_secret: null })!;
    const noCert = parseResolvedProvider({ ...SAML_ROW, saml_config: { ...SAML_ROW.saml_config, certificates: [] } })!;
    expect(buildDefaultSsoEntries({ providers: [noSecret, noCert], fingerprint: 'x' }, BASE)).toEqual([]);
  });

  test('finds a provider by its plugin id', () => {
    expect(findSsoProvider(resolved, 'sso-acme')?.slug).toBe('acme');
    expect(findSsoProvider(resolved, 'sso-gone')).toBeNull();
    expect(findSsoProvider(resolved, null)).toBeNull();
  });
});
