/**
 * Workspace → Single sign-on — the model (EID-1.2, #5012).
 *
 * The pure helpers of `lib/workspace-sso.ts`: how a provider's state is worded, what removing it
 * costs, how a DNS check is headed (a failed lookup is "Could not check", never "Verified"), the
 * create and update request bodies (no workspace, no unchanged field, no blank secret), the proxy's
 * path allowlist, and the email-domain reader the sign-in page uses.
 */

import {
  buildWorkspaceSsoCreatePayload,
  buildWorkspaceSsoUpdatePayload,
  emailDomainForSso,
  EMPTY_WORKSPACE_SSO_DRAFT,
  ssoCheckHeading,
  ssoDomainSummary,
  ssoProtocolLabel,
  ssoProviderStatus,
  ssoRemoveImpact,
  workspaceSsoEditFrom,
  workspaceSsoUpstreamPath,
  type WorkspaceSsoProvider,
} from '../lib/workspace-sso';

const ID = '8dc47ff5-488b-44d0-9d72-ebf5ad0de3b2';

const OIDC: WorkspaceSsoProvider = {
  id: ID,
  slug: 'acme-okta',
  plugin_provider_id: 'sso-acme-okta',
  identity_kind: 'sso:acme-okta',
  protocol: 'oidc',
  display_name: 'Acme Okta',
  issuer: 'https://acme.okta.com',
  tenant_id: 't-1',
  tenant_name: 'Acme',
  oidc_config: { client_id: 'apiome' },
  saml_config: null,
  has_client_secret: true,
  has_sp_private_key: false,
  enabled: false,
  routable: false,
  default_role_slug: 'editor',
  member_count: 0,
  domains: [],
};

const SAML: WorkspaceSsoProvider = {
  ...OIDC,
  slug: 'acme-saml',
  protocol: 'saml',
  oidc_config: null,
  saml_config: { email_source: 'attribute', email_attribute: 'mail' },
  has_client_secret: false,
  has_sp_private_key: true,
  default_role_slug: null,
};

describe('how a provider is described', () => {
  it('is Live only when enabled with a verified domain', () => {
    expect(ssoProviderStatus({ enabled: true, routable: true })).toMatchObject({ kind: 'live', label: 'Live' });
    expect(ssoProviderStatus({ enabled: true, routable: false })).toMatchObject({
      kind: 'needs-domain',
      label: 'Needs a verified domain',
    });
    expect(ssoProviderStatus({ enabled: false, routable: false })).toMatchObject({ kind: 'off', label: 'Disabled' });
  });

  it('names the protocol and counts verified domains', () => {
    expect(ssoProtocolLabel('oidc')).toBe('OIDC');
    expect(ssoProtocolLabel('saml')).toBe('SAML 2.0');
    expect(ssoDomainSummary([])).toBe('None yet');
    expect(ssoDomainSummary([{ verified: true }, { verified: false }])).toBe('1 of 2 verified');
  });

  it('says what removing a provider costs', () => {
    expect(ssoRemoveImpact(0)).toBe('No members have signed in through this provider.');
    expect(ssoRemoveImpact(1)).toMatch(/^1 member has signed in through this provider\./);
    expect(ssoRemoveImpact(12)).toMatch(/^12 members have signed in through this provider\./);
  });

  it('never heads a failed lookup as verified', () => {
    expect(ssoCheckHeading({ status: 'verified' })).toEqual({ title: 'Verified', tone: 'ok' });
    expect(ssoCheckHeading({ status: 'not-found' }).title).toBe('Record not found');
    expect(ssoCheckHeading({ status: 'mismatch' }).title).toBe('Record has another value');
    expect(ssoCheckHeading({ status: 'could-not-check' })).toEqual({ title: 'Could not check', tone: 'warn' });
  });
});

describe('the create body', () => {
  it('sends an OIDC provider without a workspace', () => {
    const body = buildWorkspaceSsoCreatePayload({
      ...EMPTY_WORKSPACE_SSO_DRAFT,
      displayName: ' Acme Okta ',
      slug: 'acme-okta',
      issuer: 'https://acme.okta.com ',
      clientId: 'apiome',
      clientSecret: 's3cret',
      defaultRole: 'viewer',
    });
    expect(body).toEqual({
      protocol: 'oidc',
      slug: 'acme-okta',
      display_name: 'Acme Okta',
      issuer: 'https://acme.okta.com',
      client_id: 'apiome',
      client_secret: 's3cret',
      default_role_slug: 'viewer',
    });
    expect(body).not.toHaveProperty('tenant_id');
  });

  it('sends pasted SAML metadata in preference to the URL, and no default role when none is chosen', () => {
    const body = buildWorkspaceSsoCreatePayload({
      ...EMPTY_WORKSPACE_SSO_DRAFT,
      protocol: 'saml',
      displayName: 'Acme SAML',
      slug: 'acme-saml',
      metadataUrl: 'https://idp.example.com/metadata',
      metadataXml: '<md:EntityDescriptor/>',
      emailSource: 'attribute',
      emailAttribute: ' mail ',
    });
    expect(body).toEqual({
      protocol: 'saml',
      slug: 'acme-saml',
      display_name: 'Acme SAML',
      metadata_xml: '<md:EntityDescriptor/>',
      email_source: 'attribute',
      email_attribute: 'mail',
    });
  });
});

describe('the update body', () => {
  it('starts from the stored settings with every secret blank', () => {
    expect(workspaceSsoEditFrom(OIDC)).toMatchObject({
      displayName: 'Acme Okta',
      defaultRole: 'editor',
      clientId: 'apiome',
      clientSecret: '',
    });
    expect(workspaceSsoEditFrom(SAML)).toMatchObject({
      emailSource: 'attribute',
      emailAttribute: 'mail',
      spPrivateKey: '',
      defaultRole: '',
    });
  });

  it('is empty when nothing changed', () => {
    expect(buildWorkspaceSsoUpdatePayload(OIDC, workspaceSsoEditFrom(OIDC))).toEqual({});
    expect(buildWorkspaceSsoUpdatePayload(SAML, workspaceSsoEditFrom(SAML))).toEqual({});
  });

  it('carries only what changed, and a secret only when one was typed', () => {
    const edit = { ...workspaceSsoEditFrom(OIDC), displayName: 'Acme SSO', defaultRole: '' };
    expect(buildWorkspaceSsoUpdatePayload(OIDC, edit)).toEqual({ display_name: 'Acme SSO', default_role_slug: null });
    expect(buildWorkspaceSsoUpdatePayload(OIDC, { ...workspaceSsoEditFrom(OIDC), clientSecret: 'rotated' })).toEqual({
      client_secret: 'rotated',
    });
    expect(buildWorkspaceSsoUpdatePayload(OIDC, { ...workspaceSsoEditFrom(OIDC), clientId: 'apiome-2' })).toEqual({
      client_id: 'apiome-2',
    });
  });

  it('re-reads SAML metadata only when given, and moves the email source', () => {
    const base = workspaceSsoEditFrom(SAML);
    expect(buildWorkspaceSsoUpdatePayload(SAML, { ...base, metadataUrl: ' https://idp.example.com/m ' })).toEqual({
      metadata_url: 'https://idp.example.com/m',
    });
    expect(buildWorkspaceSsoUpdatePayload(SAML, { ...base, emailSource: 'nameid' })).toEqual({ email_source: 'nameid' });
    expect(buildWorkspaceSsoUpdatePayload(SAML, { ...base, emailAttribute: 'email' })).toEqual({
      email_attribute: 'email',
    });
    expect(buildWorkspaceSsoUpdatePayload(SAML, { ...base, spPrivateKey: '-----BEGIN PRIVATE KEY-----' })).toEqual({
      sp_private_key: '-----BEGIN PRIVATE KEY-----',
    });
  });
});

describe('the proxy allowlist', () => {
  it.each([
    ['GET', [], 'sso/providers'],
    ['POST', [], 'sso/providers'],
    ['GET', [ID], `sso/providers/${ID}`],
    ['PATCH', [ID], `sso/providers/${ID}`],
    ['DELETE', [ID], `sso/providers/${ID}`],
    ['POST', [ID, 'domains'], `sso/providers/${ID}/domains`],
    ['DELETE', [ID, 'domains', 'Acme.com'], `sso/providers/${ID}/domains/acme.com`],
    ['POST', [ID, 'domains', 'acme.com', 'verify'], `sso/providers/${ID}/domains/acme.com/verify`],
  ])('forwards %s %j', (method, segments, expected) => {
    expect(workspaceSsoUpstreamPath(method, segments)).toBe(expected);
  });

  it.each([
    ['PUT', []],
    ['DELETE', []],
    ['GET', ['not-a-uuid']],
    ['GET', [ID, 'domains']],
    ['POST', [ID, 'domains', 'acme.com']],
    ['POST', [ID, 'domains', '..', 'verify']],
    ['POST', [ID, 'domains', 'acme.com/../../x', 'verify']],
    ['GET', ['..', '..', 'members']],
    ['POST', [ID, 'provision']],
  ])('refuses %s %j', (method, segments) => {
    expect(workspaceSsoUpstreamPath(method, segments)).toBeNull();
  });
});

describe('reading an email domain on the sign-in page', () => {
  it('waits for a whole address', () => {
    expect(emailDomainForSso('ada')).toBeNull();
    expect(emailDomainForSso('ada@')).toBeNull();
    expect(emailDomainForSso('ada@acme')).toBeNull();
    expect(emailDomainForSso('ada@acme.c')).toBeNull();
    expect(emailDomainForSso('ada@acme .com')).toBeNull();
  });

  it('returns the lower-cased domain', () => {
    expect(emailDomainForSso(' Ada@Acme.COM ')).toBe('acme.com');
    expect(emailDomainForSso('ada@mail.acme.co.uk')).toBe('mail.acme.co.uk');
  });
});
