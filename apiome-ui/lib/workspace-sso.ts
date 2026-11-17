/**
 * Workspace → Single sign-on — shapes and pure helpers (EID-1.2, #5012).
 *
 * Mirrors the REST surface `/v1/tenants/{t}/sso/providers`
 * (`apiome-rest/src/app/tenant_sso_routes.py`) so the page (`/ade/dashboard/sso`), its proxy
 * (`/api/workspace-sso`) and their tests share one definition. The provider shape, the slug
 * suggestion and the values an IdP admin needs are the admin console's (`lib/auth/admin-sso.ts`):
 * it is the same provider, seen by its owner instead of the installation admin.
 *
 * Nothing here holds or returns a secret: secrets go out once, write-only, in a create or update
 * payload, and come back only as `has_client_secret` / `has_sp_private_key`.
 */

import {
  buildSsoCreatePayload,
  EMPTY_SSO_DRAFT,
  type AdminSsoDomainView,
  type AdminSsoDraft,
  type AdminSsoProviderView,
} from './auth/admin-sso';

export { ssoSetupDetails, suggestSsoSlug, type SsoSetupDetail } from './auth/admin-sso';

/** One email domain of a provider, with where its DNS challenge goes. */
export interface WorkspaceSsoDomain extends AdminSsoDomainView {
  /** The TXT record to publish: `_apiome-challenge.<domain>`. */
  record_name: string;
}

/** A provider as its workspace's owners see it. */
export interface WorkspaceSsoProvider extends Omit<AdminSsoProviderView, 'domains'> {
  domains: WorkspaceSsoDomain[];
  /** The role a member gets on first sign-in, or null for the workspace default. */
  default_role_slug: string | null;
  /** Members of this workspace who have signed in through this provider. */
  member_count: number;
}

/** What one DNS check found (`check` of the verify response). */
export interface SsoDomainCheck {
  status: 'verified' | 'not-found' | 'mismatch' | 'could-not-check';
  verified: boolean;
  record_name: string;
  expected: string;
  /** The TXT values found, or one line saying why the lookup failed. */
  observed: string[];
  message: string;
}

/** The verify response: the provider as it now stands, and what the check found. */
export interface SsoDomainVerifyResult {
  provider: WorkspaceSsoProvider;
  check: SsoDomainCheck;
}

/** The add-provider form: the admin console's, plus the default role and minus the workspace. */
export interface WorkspaceSsoDraft extends Omit<AdminSsoDraft, 'tenantId'> {
  /** A role slug, or '' for the workspace default. */
  defaultRole: string;
}

/** An empty add-provider form. */
export const EMPTY_WORKSPACE_SSO_DRAFT: WorkspaceSsoDraft = {
  protocol: EMPTY_SSO_DRAFT.protocol,
  displayName: '',
  slug: '',
  issuer: '',
  clientId: '',
  clientSecret: '',
  metadataUrl: '',
  metadataXml: '',
  emailSource: EMPTY_SSO_DRAFT.emailSource,
  emailAttribute: '',
  spPrivateKey: '',
  defaultRole: '',
};

/** The role nobody receives just by signing in; it is left out of the default-role choices. */
export const SSO_OWNER_ROLE_SLUG = 'owner';

/** Why a button is unavailable while a request is in flight (a disabled button says why). */
export const SSO_BUSY_REASON = 'Wait for the current request to finish';

/** The page's route. */
export const WORKSPACE_SSO_ROUTE = '/ade/dashboard/sso';

/** Where a provider stands, as the list and the drawer say it. */
export interface SsoProviderStatus {
  /** `live` routes sign-ins; `needs-domain` is enabled without a verified domain; `off` is disabled. */
  kind: 'live' | 'needs-domain' | 'off';
  label: string;
  /** The `Badge` variant that carries it. */
  tone: 'ok' | 'warn' | 'neutral';
}

/**
 * Where a provider stands.
 *
 * @param view The provider.
 * @returns Live (enabled with a verified domain), waiting for a verified domain, or disabled.
 */
export function ssoProviderStatus(view: Pick<WorkspaceSsoProvider, 'enabled' | 'routable'>): SsoProviderStatus {
  if (view.routable) return { kind: 'live', label: 'Live', tone: 'ok' };
  if (view.enabled) return { kind: 'needs-domain', label: 'Needs a verified domain', tone: 'warn' };
  return { kind: 'off', label: 'Disabled', tone: 'neutral' };
}

/**
 * A provider's protocol as people say it.
 *
 * @param protocol `oidc` or `saml`.
 * @returns `OIDC` or `SAML 2.0`.
 */
export function ssoProtocolLabel(protocol: 'oidc' | 'saml'): string {
  return protocol === 'oidc' ? 'OIDC' : 'SAML 2.0';
}

/**
 * How many of a provider's domains are verified, as the list says it.
 *
 * @param domains The provider's domains.
 * @returns e.g. `1 of 2 verified`, or `None yet`.
 */
export function ssoDomainSummary(domains: ReadonlyArray<Pick<WorkspaceSsoDomain, 'verified'>>): string {
  if (domains.length === 0) return 'None yet';
  const verified = domains.filter((domain) => domain.verified).length;
  return `${verified} of ${domains.length} verified`;
}

/**
 * What removing a provider costs, for the confirmation.
 *
 * @param memberCount Members who have signed in through it.
 * @returns The impact sentence.
 */
export function ssoRemoveImpact(memberCount: number): string {
  if (memberCount <= 0) return 'No members have signed in through this provider.';
  const who = memberCount === 1 ? '1 member has' : `${memberCount} members have`;
  return `${who} signed in through this provider. They keep their accounts but can no longer sign in this way.`;
}

/**
 * The heading of a DNS check's result.
 *
 * A lookup that failed reads "Could not check" — never "verified", and not "not found" either:
 * nothing is known about the record.
 *
 * @param check The check.
 * @returns The heading and the `Alert` variant that carries it.
 */
export function ssoCheckHeading(check: Pick<SsoDomainCheck, 'status'>): { title: string; tone: 'ok' | 'warn' | 'danger' } {
  switch (check.status) {
    case 'verified':
      return { title: 'Verified', tone: 'ok' };
    case 'not-found':
      return { title: 'Record not found', tone: 'warn' };
    case 'mismatch':
      return { title: 'Record has another value', tone: 'danger' };
    default:
      return { title: 'Could not check', tone: 'warn' };
  }
}

/**
 * Turn the form into the `POST /v1/tenants/{t}/sso/providers` body. Blank optional fields are left
 * out; the REST surface does the real validation and answers with a stable `sso-*` code. The
 * workspace is never sent: REST takes it from the session.
 *
 * @param draft The form.
 * @returns The request body.
 */
export function buildWorkspaceSsoCreatePayload(draft: WorkspaceSsoDraft): Record<string, unknown> {
  const { defaultRole, ...rest } = draft;
  const payload = buildSsoCreatePayload({ ...rest, tenantId: '' });
  if (defaultRole.trim()) payload.default_role_slug = defaultRole.trim();
  return payload;
}

/** The editable, non-secret settings of a stored provider (the drawer's Configure tab). */
export interface WorkspaceSsoEdit {
  displayName: string;
  defaultRole: string;
  /** OIDC. */
  clientId: string;
  /** OIDC, write-only: '' keeps the stored secret. */
  clientSecret: string;
  /** SAML: '' keeps the stored metadata. */
  metadataUrl: string;
  metadataXml: string;
  emailSource: 'nameid' | 'attribute';
  emailAttribute: string;
  /** SAML, write-only: '' keeps the stored key. */
  spPrivateKey: string;
}

const text = (value: unknown): string => (typeof value === 'string' ? value : '');

/**
 * The Configure form for a stored provider. Secrets start blank — they are never read back.
 *
 * @param view The provider.
 * @returns The form's starting values.
 */
export function workspaceSsoEditFrom(view: WorkspaceSsoProvider): WorkspaceSsoEdit {
  const saml = view.saml_config ?? {};
  return {
    displayName: view.display_name,
    defaultRole: view.default_role_slug ?? '',
    clientId: text(view.oidc_config?.client_id),
    clientSecret: '',
    metadataUrl: '',
    metadataXml: '',
    emailSource: saml.email_source === 'attribute' ? 'attribute' : 'nameid',
    emailAttribute: text(saml.email_attribute),
    spPrivateKey: '',
  };
}

/**
 * The `PATCH` body for a Configure save: only what changed. A blank secret or metadata field
 * means "keep what is stored" and is left out.
 *
 * @param view The provider as stored.
 * @param edit The form.
 * @returns The request body; empty when nothing changed.
 */
export function buildWorkspaceSsoUpdatePayload(view: WorkspaceSsoProvider, edit: WorkspaceSsoEdit): Record<string, unknown> {
  const before = workspaceSsoEditFrom(view);
  const payload: Record<string, unknown> = {};
  if (edit.displayName.trim() !== before.displayName) payload.display_name = edit.displayName.trim();
  if (edit.defaultRole !== before.defaultRole) payload.default_role_slug = edit.defaultRole || null;
  if (view.protocol === 'oidc') {
    if (edit.clientId.trim() !== before.clientId) payload.client_id = edit.clientId.trim();
    if (edit.clientSecret.trim()) payload.client_secret = edit.clientSecret;
    return payload;
  }
  if (edit.metadataXml.trim()) payload.metadata_xml = edit.metadataXml;
  else if (edit.metadataUrl.trim()) payload.metadata_url = edit.metadataUrl.trim();
  if (edit.emailSource !== before.emailSource) payload.email_source = edit.emailSource;
  const attribute = edit.emailSource === 'attribute' ? edit.emailAttribute.trim() : '';
  if (edit.emailSource === 'attribute' && attribute !== before.emailAttribute) payload.email_attribute = attribute;
  if (edit.spPrivateKey.trim()) payload.sp_private_key = edit.spPrivateKey;
  return payload;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Whole labels only: a looser pattern would let `..` through as a "domain" and have the URL
// normalised onto a different REST path.
const DOMAIN_LABEL = '[a-z0-9](?:[a-z0-9-]*[a-z0-9])?';
const DOMAIN = new RegExp(`^(?=.{1,253}$)${DOMAIN_LABEL}(?:\\.${DOMAIN_LABEL})+$`, 'i');

/** The method and path shapes the REST surface defines below `/sso/providers`. */
const ALLOWED: ReadonlyArray<{ methods: readonly string[]; shape: (s: string[]) => boolean }> = [
  { methods: ['GET', 'POST'], shape: (s) => s.length === 0 },
  { methods: ['GET', 'PATCH', 'DELETE'], shape: (s) => s.length === 1 && UUID.test(s[0]) },
  { methods: ['POST'], shape: (s) => s.length === 2 && UUID.test(s[0]) && s[1] === 'domains' },
  {
    methods: ['DELETE'],
    shape: (s) => s.length === 3 && UUID.test(s[0]) && s[1] === 'domains' && DOMAIN.test(s[2]),
  },
  {
    methods: ['POST'],
    shape: (s) => s.length === 4 && UUID.test(s[0]) && s[1] === 'domains' && DOMAIN.test(s[2]) && s[3] === 'verify',
  },
];

/**
 * The path below `/v1/tenants/{slug}` for a proxied request, or null when the method and path are
 * not ones the REST surface defines — so the proxy cannot be steered at any other tenant route.
 *
 * @param method The HTTP method.
 * @param segments The `[[...path]]` segments after `/api/workspace-sso`.
 * @returns `sso/providers…`, or null.
 */
export function workspaceSsoUpstreamPath(method: string, segments: readonly string[]): string | null {
  const verb = method.toUpperCase();
  const parts = [...segments];
  if (!ALLOWED.some((rule) => rule.methods.includes(verb) && rule.shape(parts))) return null;
  return `sso/providers${parts.map((part) => `/${encodeURIComponent(part.toLowerCase())}`).join('')}`;
}

/**
 * The email domain of what someone typed into a sign-in field, or null while it is not yet an
 * address worth looking up (`ada@acme` has no top-level label yet).
 *
 * @param email The field's value.
 * @returns The lower-cased domain, or null.
 */
export function emailDomainForSso(email: string): string | null {
  const match = /^[^\s@]+@([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})$/i.exec(email.trim());
  return match ? match[1].toLowerCase() : null;
}
