/**
 * MCP endpoint-detail "Credentials" tab — shared types & pure helpers (V2-MCP-24.6 / MCAT-10.6,
 * #3702).
 *
 * The Credentials tab lets the owner set or replace the outbound credential apiome-rest sends to
 * an MCP server (a bearer token, one custom header, or a pasted OAuth 2.1 access token), shows the
 * stored credential **masked**, and clears it. It talks to the credential routes of MCAT-6.5
 * (`GET` / `PUT` / `DELETE /api/mcp/endpoints/{id}/credentials`), whose every response is the
 * *redacted* status — no response carries the secret, and nothing here keeps one past the request
 * that stores it.
 *
 * This module holds the *pure*, React-free half — the redacted status shape and its reader, the
 * form shape, the inline validation (mirroring apiome-rest's `validate_credential_payload`, so a
 * malformed or injection-bearing secret is refused before it leaves the browser), the request-body
 * builder (shared with the Add MCP server dialog) and the summary lines the panel shows — so it can
 * be unit-tested without React or the network. `McpEndpointCredentials` consumes it.
 */

import {
  MCP_AUTH_TYPE_OPTIONS,
  buildCredentialBody,
  emptyMcpImportForm,
  type McpAuthType,
  type McpCredentialBody,
} from './mcpImportFlow';

/** The schemes the tab can store. `none` is reached by clearing, never by saving. */
export type McpCredentialAuthType = Exclude<McpAuthType, 'none'>;

/** Option list for the auth-type select: every scheme the Add MCP server dialog offers, minus `none`. */
export const MCP_CREDENTIAL_AUTH_OPTIONS: ReadonlyArray<{ value: McpCredentialAuthType; label: string }> =
  MCP_AUTH_TYPE_OPTIONS.filter(
    (option): option is { value: McpCredentialAuthType; label: string } => option.value !== 'none',
  );

/**
 * What the panel draws in place of a stored secret. apiome-rest's own placeholder is `********`;
 * the mockup draws bullets, and the two are equivalent because neither is the secret.
 */
export const MCP_CREDENTIAL_MASK = '••••••••';

/** The note under the form, spelled once so the panel and its test agree. */
export const MCP_CREDENTIAL_ENCRYPTION_NOTE =
  'Secrets are encrypted at rest (AES-256-GCM) before they are stored and are never shown again — ' +
  'not in this page, not in the API. Reading the credential back returns only its type and a mask.';

/** The redacted credential status apiome-rest returns (never the secret). */
export interface McpCredentialStatus {
  /** The endpoint the status is for. */
  endpointId: string | null;
  /** The configured scheme — `none` when no credential is stored. */
  authType: string;
  /** A sealed secret is stored. */
  configured: boolean;
  /** The sealing key's version, when a secret is stored. */
  keyVersion: number | null;
  /** Non-secret OAuth discovery metadata (MCAT-6.3 / 6.4); `{}` when none. */
  oauthMetadata: Record<string, unknown>;
  /** When the stored token was last refreshed (ISO), OAuth only. */
  lastRefreshedAt: string | null;
  /** When the credential row was created (ISO). */
  createdAt: string | null;
  /** When the credential row was last written (ISO). */
  updatedAt: string | null;
}

/** The anonymous status: no credential stored. */
export const MCP_CREDENTIAL_NONE: McpCredentialStatus = {
  endpointId: null,
  authType: 'none',
  configured: false,
  keyVersion: null,
  oauthMetadata: {},
  lastRefreshedAt: null,
  createdAt: null,
  updatedAt: null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function int(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : null;
}

/**
 * Read the redacted status out of a credential route's response.
 *
 * Accepts the `{ success, credential }` envelope the `GET`/`PUT` routes return, or the bare
 * credential object. The secret has no field to arrive in, so nothing here could keep one.
 *
 * @param payload The parsed JSON body.
 * @returns The status, or `null` when the body is not a credential status at all.
 */
export function mcpCredentialStatusFromPayload(payload: unknown): McpCredentialStatus | null {
  if (!isRecord(payload)) return null;
  const record = isRecord(payload.credential) ? payload.credential : payload;
  if (!('auth_type' in record) && !('configured' in record)) return null;
  const configured = record.configured === true;
  return {
    endpointId: str(record.endpoint_id),
    authType: str(record.auth_type) ?? 'none',
    configured,
    keyVersion: configured ? int(record.key_version) : null,
    oauthMetadata: isRecord(record.oauth_metadata) ? record.oauth_metadata : {},
    lastRefreshedAt: str(record.last_refreshed_at),
    createdAt: str(record.created_at),
    updatedAt: str(record.updated_at),
  };
}

/**
 * The human label of a stored scheme, as the Add MCP server dialog names it.
 *
 * @param authType The scheme (`bearer`, `header`, `oauth2`, `env` or `none`).
 * @returns The label; an unknown scheme is returned as typed.
 */
export function mcpCredentialAuthLabel(authType: string | null | undefined): string {
  const value = (authType ?? '').trim().toLowerCase();
  if (!value || value === 'none') return 'None (anonymous)';
  if (value === 'oauth2') return 'OAuth 2.1';
  if (value === 'env') return 'Environment variables';
  const option = MCP_CREDENTIAL_AUTH_OPTIONS.find((candidate) => candidate.value === value);
  return option ? option.label : (authType as string);
}

/** The two lines the "Stored credential" card shows. */
export interface McpCredentialSummary {
  /** The headline — what is stored. */
  title: string;
  /** What that means for discovery, the sweep and test calls. */
  detail: string;
}

/**
 * Describe a status in two lines.
 *
 * @param status The redacted status.
 * @returns The headline and its explanation.
 */
export function mcpCredentialSummary(status: McpCredentialStatus): McpCredentialSummary {
  if (!status.configured) {
    return {
      title: 'No credential stored',
      detail: 'Discovery, the scheduled sweep and Test calls reach this server anonymously.',
    };
  }
  const label = mcpCredentialAuthLabel(status.authType);
  if (status.authType === 'oauth2') {
    return {
      title: `${label} token stored`,
      detail: 'Sent as a bearer token on discovery, the scheduled sweep and Test calls.',
    };
  }
  if (status.authType === 'header') {
    return {
      title: `${label} stored`,
      detail: 'Sent as the named request header on discovery, the scheduled sweep and Test calls.',
    };
  }
  return {
    title: `${label} stored`,
    detail: 'Sent in the Authorization header on discovery, the scheduled sweep and Test calls.',
  };
}

/**
 * The meta line under the mask: which key sealed the secret and when it was last written.
 *
 * @param status The redacted status.
 * @param format Formats an ISO timestamp for display.
 * @returns e.g. `Encrypted with key v2 · Updated 8 Nov 2026, 13:00`, or `null` when nothing is stored.
 */
export function mcpCredentialMetaLine(
  status: McpCredentialStatus,
  format: (iso: string) => string,
): string | null {
  if (!status.configured) return null;
  const parts: string[] = [];
  if (status.keyVersion !== null) parts.push(`Encrypted with key v${status.keyVersion}`);
  const written = status.updatedAt ?? status.createdAt;
  if (written) parts.push(`Updated ${format(written)}`);
  return parts.length ? parts.join(' · ') : null;
}

// --- The form -------------------------------------------------------------------------------

/** What the owner types to set or replace a credential. */
export interface McpCredentialForm {
  /** The scheme to store. */
  authType: McpCredentialAuthType;
  /** The bearer / OAuth access token, or the header value for `header`. Never persisted here. */
  secret: string;
  /** The header name (only used when `authType === 'header'`). */
  headerName: string;
}

/** A fresh, empty form. */
export function emptyMcpCredentialForm(authType: McpCredentialAuthType = 'bearer'): McpCredentialForm {
  return { authType, secret: '', headerName: '' };
}

/**
 * RFC 7230 `token` characters — what a header name may be made of. apiome-rest refuses a header
 * name outside this set (and any CR / LF) with `422`; checking here says so before the request.
 */
const HEADER_NAME_RE = /^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/;

/**
 * Validate the form before it is sent, mirroring apiome-rest's `validate_credential_payload`.
 *
 * @param form The form state.
 * @returns A message to show, or `null` when the form can be sent.
 */
export function validateMcpCredentialForm(form: McpCredentialForm): string | null {
  const secret = form.secret ?? '';
  if (!secret.trim()) {
    return form.authType === 'header'
      ? 'Enter the header value.'
      : 'Enter the access token for the selected auth type.';
  }
  if (/[\r\n]/.test(secret)) return 'The secret cannot contain line breaks.';
  if (form.authType === 'header') {
    const name = (form.headerName ?? '').trim();
    if (!name) return 'Enter the header name.';
    if (!HEADER_NAME_RE.test(name)) {
      return 'The header name may only use letters, digits and the characters !#$%&\'*+.^_`|~-.';
    }
    if (name.toLowerCase() === 'authorization') {
      return 'Use the Bearer token auth type for an Authorization header.';
    }
  }
  return null;
}

/**
 * Build the body of `PUT /api/mcp/endpoints/{id}/credentials` — the same shape the Add MCP server
 * dialog sends, built by the same function so the two never drift.
 *
 * @param form A form {@link validateMcpCredentialForm} accepted.
 * @returns The request body.
 */
export function buildMcpCredentialBody(form: McpCredentialForm): McpCredentialBody {
  const body = buildCredentialBody({
    ...emptyMcpImportForm(),
    authType: form.authType,
    authToken: form.secret,
    authHeaderName: form.headerName,
  });
  if (!body) throw new Error(`Unsupported auth type: ${form.authType}`);
  return body;
}

/**
 * The label of the input that takes the secret, per scheme.
 *
 * @param authType The selected scheme.
 * @returns `Header value` for a header, otherwise `Access token`.
 */
export function mcpCredentialSecretLabel(authType: McpCredentialAuthType): string {
  return authType === 'header' ? 'Header value' : 'Access token';
}

/** The confirm dialog shown before a stored credential is cleared. */
export const MCP_CREDENTIAL_CLEAR_CONFIRM = {
  title: 'Clear this credential?',
  message:
    'The stored secret is deleted and cannot be recovered. Discovery, the scheduled sweep and ' +
    'Test calls will reach this server anonymously until a new credential is saved.',
  confirmLabel: 'Clear credential',
  cancelLabel: 'Keep it',
} as const;
