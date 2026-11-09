/**
 * Model for connecting an OAuth-protected MCP server (V2-MCP-20.4 / MCAT-6.4, #3680).
 *
 * A discovery run that meets a `401` stores the server's OAuth metadata (MCAT-6.3). The
 * Credentials tab (V2-MCP-24.6) then offers **Connect with OAuth**: apiome-rest returns an
 * authorization URL (PKCE S256, the
 * RFC 8707 resource, a sealed state), the browser goes there, the user consents, and the
 * authorization server sends the browser back to {@link MCP_OAUTH_CALLBACK_PATH}. That page posts
 * the query parameters to apiome-rest, which exchanges the code and stores the tokens sealed.
 *
 * Everything here is pure, so the section and the callback page stay thin and testable. Nothing
 * here ever sees a token — the credential status is the redacted one.
 */

/** The UI route the authorization server redirects back to. Registered as the client's redirect URI. */
export const MCP_OAUTH_CALLBACK_PATH = '/ade/dashboard/mcp/oauth/callback';

/** What the Credentials tab knows about an endpoint's OAuth connection. */
export interface McpOAuthStatus {
  /** Discovery found an authorization server (the section is shown only then). */
  discovered: boolean;
  /** The authorization server's issuer URL. */
  issuer: string | null;
  /** The server has a registration endpoint, so no client id is needed. */
  dynamicRegistration: boolean;
  /** The server advertises PKCE S256 (Apiome refuses to connect without it). */
  pkceSupported: boolean;
  /** An OAuth token is stored. */
  connected: boolean;
  /** When the stored access token expires (ISO), or `null` when unknown. */
  expiresAt: string | null;
  /** The stored token carries a refresh token, so Apiome renews it by itself. */
  refreshable: boolean;
  /** The client id the token belongs to. */
  clientId: string | null;
  /** The granted scope. */
  scope: string | null;
  /** The reason the last automatic refresh failed, or `null`. */
  lastRefreshError: string | null;
}

/** The authorization server's answer, as the callback page reads it from its URL. */
export interface McpOAuthCallbackParams {
  state: string;
  code: string | null;
  error: string | null;
  error_description: string | null;
  iss: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

/**
 * Read the OAuth connection state out of a redacted credential status.
 *
 * @param credential The `credential` object from `GET /api/mcp/endpoints/{id}/credentials`.
 * @returns The status; `discovered` is `false` when no OAuth metadata is stored.
 */
export function mcpOAuthStatusFromCredential(credential: unknown): McpOAuthStatus {
  const record = isRecord(credential) ? credential : {};
  const metadata = isRecord(record.oauth_metadata) ? record.oauth_metadata : {};
  const token = isRecord(metadata.token) ? metadata.token : {};
  const refreshError = isRecord(token.last_refresh_error) ? token.last_refresh_error : null;
  return {
    discovered: Boolean(str(metadata.authorization_endpoint) && str(metadata.token_endpoint)),
    issuer: str(metadata.issuer),
    dynamicRegistration: Boolean(str(metadata.registration_endpoint)),
    pkceSupported: metadata.pkce_s256_supported === true,
    connected: record.auth_type === 'oauth2' && record.configured === true,
    expiresAt: str(token.expires_at),
    refreshable: token.refreshable === true,
    clientId: str(token.client_id),
    scope: str(token.scope),
    lastRefreshError: refreshError ? str(refreshError.message) ?? str(refreshError.code) : null,
  };
}

/**
 * The redirect URI for this browser's origin.
 *
 * @param origin `window.location.origin`.
 * @returns The absolute callback URL.
 */
export function mcpOAuthRedirectUri(origin: string): string {
  return `${origin.replace(/\/+$/, '')}${MCP_OAUTH_CALLBACK_PATH}`;
}

/**
 * Build the body of `POST /api/mcp/endpoints/{id}/oauth/authorize`.
 *
 * @param redirectUri The callback URL from {@link mcpOAuthRedirectUri}.
 * @param clientId A client id typed by the user (blank → Dynamic Client Registration).
 * @returns The request body.
 */
export function mcpOAuthAuthorizeBody(redirectUri: string, clientId: string): Record<string, string> {
  const body: Record<string, string> = { redirect_uri: redirectUri };
  if (clientId.trim()) body.client_id = clientId.trim();
  return body;
}

/**
 * Read the authorization server's answer from the callback page's query string.
 *
 * @param search `window.location.search` (or a `URLSearchParams`).
 * @returns The parameters, or `null` when there is no `state` (not an OAuth redirect).
 */
export function mcpOAuthCallbackParams(search: string | URLSearchParams): McpOAuthCallbackParams | null {
  const params = typeof search === 'string' ? new URLSearchParams(search) : search;
  const state = params.get('state');
  if (!state) return null;
  return {
    state,
    code: params.get('code'),
    error: params.get('error'),
    error_description: params.get('error_description'),
    iss: params.get('iss'),
  };
}

/**
 * Where the callback page sends the user once the connection is stored.
 *
 * @param endpointId The connected endpoint.
 * @returns The endpoint's Credentials tab (V2-MCP-24.6), where the OAuth connection section lives.
 */
export function mcpOAuthReturnPath(endpointId: string): string {
  return `/ade/dashboard/mcp/${encodeURIComponent(endpointId)}?tab=credentials`;
}

/**
 * One line describing a stored token's expiry, e.g. `Expires 8 Nov 2026, 13:00 · renews automatically`.
 *
 * @param status The connection status.
 * @param format Formats an ISO timestamp for display.
 * @returns The line, or `null` when not connected.
 */
export function mcpOAuthExpiryLine(
  status: McpOAuthStatus,
  format: (iso: string) => string,
): string | null {
  if (!status.connected) return null;
  const expiry = status.expiresAt ? `Expires ${format(status.expiresAt)}` : 'No expiry reported';
  return status.refreshable ? `${expiry} · renews automatically` : `${expiry} · connect again when it expires`;
}
