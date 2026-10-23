/**
 * The admin console's SSO providers section — shapes and pure helpers (EID-1.1, #5011).
 *
 * Mirrors the REST surface `/v1/admin/sso/providers` (`apiome-rest/src/app/sso_provider_routes.py`)
 * so the card (`src/app/admin/dashboard/settings/SsoProvidersCard.tsx`) and its tests share one
 * definition. Nothing here holds or returns a secret: secrets go out once, write-only, in a create
 * or update payload, and come back only as `has_client_secret` / `has_sp_private_key`.
 */

/** One email domain of a provider. */
export interface AdminSsoDomainView {
  domain: string;
  verified: boolean;
  verified_at: string | null;
  verified_by: string | null;
  verification_token: string;
}

/** A provider as the admin console sees it. */
export interface AdminSsoProviderView {
  id: string;
  slug: string;
  plugin_provider_id: string;
  identity_kind: string;
  protocol: 'oidc' | 'saml';
  display_name: string;
  issuer: string;
  tenant_id: string | null;
  tenant_name: string | null;
  oidc_config: Record<string, unknown> | null;
  saml_config: Record<string, unknown> | null;
  has_client_secret: boolean;
  has_sp_private_key: boolean;
  enabled: boolean;
  routable: boolean;
  domains: AdminSsoDomainView[];
}

/** The add-provider form, before it becomes a request. */
export interface AdminSsoDraft {
  protocol: 'oidc' | 'saml';
  displayName: string;
  slug: string;
  tenantId: string;
  issuer: string;
  clientId: string;
  clientSecret: string;
  metadataUrl: string;
  metadataXml: string;
  emailSource: 'nameid' | 'attribute';
  emailAttribute: string;
  spPrivateKey: string;
}

/** An empty form. */
export const EMPTY_SSO_DRAFT: AdminSsoDraft = {
  protocol: 'oidc',
  displayName: '',
  slug: '',
  tenantId: '',
  issuer: '',
  clientId: '',
  clientSecret: '',
  metadataUrl: '',
  metadataXml: '',
  emailSource: 'nameid',
  emailAttribute: '',
  spPrivateKey: '',
};

/** One value an IdP admin copies into their IdP. */
export interface SsoSetupDetail {
  label: string;
  value: string;
}

/**
 * Suggest a slug from a display name: lower-case, hyphenated, 28 characters at most.
 *
 * @param name The display name typed so far.
 * @returns A slug the REST surface would accept, or '' when nothing usable remains.
 */
export function suggestSsoSlug(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFKD')
    // Drop the combining marks NFKD splits off (ü → u + ¨), so they do not become hyphens.
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 28)
    .replace(/-+$/, '');
}

/**
 * What the IdP admin needs from Apiome to set up the connection.
 *
 * @param origin The app's origin, e.g. `https://app.example.com`.
 * @param view The provider.
 * @returns For OIDC the redirect URI; for SAML the ACS URL, the SP entity id and the SP metadata URL.
 */
export function ssoSetupDetails(origin: string, view: Pick<AdminSsoProviderView, 'protocol' | 'plugin_provider_id'>): SsoSetupDetail[] {
  const base = `${origin.replace(/\/+$/, '')}/api/auth`;
  const id = encodeURIComponent(view.plugin_provider_id);
  if (view.protocol === 'oidc') {
    return [{ label: 'Redirect URI', value: `${base}/sso/callback/${id}` }];
  }
  const metadata = `${base}/sso/saml2/sp/metadata?providerId=${id}`;
  return [
    { label: 'ACS URL (reply URL)', value: `${base}/sso/saml2/sp/acs/${id}` },
    { label: 'SP entity ID (audience)', value: metadata },
    { label: 'SP metadata', value: metadata },
  ];
}

/**
 * Turn the form into the `POST /v1/admin/sso/providers` body. Blank optional fields are left out;
 * the REST surface does the real validation and answers with a stable `sso-*` code.
 *
 * @param draft The form.
 * @returns The request body.
 */
export function buildSsoCreatePayload(draft: AdminSsoDraft): Record<string, unknown> {
  const trimmed = (value: string) => value.trim();
  const payload: Record<string, unknown> = {
    protocol: draft.protocol,
    slug: trimmed(draft.slug),
    display_name: trimmed(draft.displayName),
  };
  if (trimmed(draft.tenantId)) payload.tenant_id = trimmed(draft.tenantId);
  if (draft.protocol === 'oidc') {
    payload.issuer = trimmed(draft.issuer);
    payload.client_id = trimmed(draft.clientId);
    payload.client_secret = draft.clientSecret;
    return payload;
  }
  if (trimmed(draft.metadataXml)) payload.metadata_xml = draft.metadataXml;
  else payload.metadata_url = trimmed(draft.metadataUrl);
  payload.email_source = draft.emailSource;
  if (draft.emailSource === 'attribute') payload.email_attribute = trimmed(draft.emailAttribute);
  if (trimmed(draft.spPrivateKey)) payload.sp_private_key = draft.spPrivateKey;
  return payload;
}

/**
 * The message for a failed admin SSO request: the REST surface's stable `{ error, message }`, or
 * a fallback. Never echoes the request (it may carry a secret).
 *
 * @param status The HTTP status.
 * @param body The parsed response body.
 * @param fallback What to say when the body carries nothing.
 * @returns The message.
 */
export function ssoAdminErrorMessage(status: number, body: unknown, fallback: string): string {
  if (status === 401 || status === 403) return 'Your admin session has expired. Sign out and back in.';
  const detail = (body as { detail?: unknown } | null)?.detail ?? body;
  if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
    return (detail as { message: string }).message;
  }
  if (typeof detail === 'string' && detail) return detail;
  return fallback;
}
