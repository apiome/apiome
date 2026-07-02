/**
 * MCP "import source" flow — shared types & pure helpers (V2-MCP-24.1 / MCAT-10.1).
 *
 * Adding an MCP server is a new source in the existing Import dialog: the user supplies an
 * endpoint URL + transport + (optional) auth, then the dialog creates the catalog endpoint,
 * stores any credential, kicks off a discovery run, and polls it to completion — committing
 * catalog version 1 through the standard discovery/import job pipeline.
 *
 * This module holds the wire shapes and the *pure* form-validation / request-building /
 * job-interpretation helpers so they can be unit-tested without React or the network. The
 * panels (`McpImportPanel`, `McpDiscoveryPanel`) and `ImportDialog` consume them.
 */

/** Transports accepted by apiome-rest (`MCP_ENDPOINT_TRANSPORTS`). */
export type McpTransport = 'streamable_http' | 'sse' | 'stdio';

/** Auth schemes offered in the import form. `none` means no stored credential. */
export type McpAuthType = 'none' | 'bearer' | 'header' | 'oauth2';

/** Option lists for the form selects (value + human label). */
export const MCP_TRANSPORT_OPTIONS: { value: McpTransport; label: string }[] = [
  { value: 'streamable_http', label: 'Streamable HTTP' },
  { value: 'sse', label: 'Server-Sent Events (SSE)' },
  { value: 'stdio', label: 'Standard I/O (stdio)' },
];

export const MCP_AUTH_TYPE_OPTIONS: { value: McpAuthType; label: string }[] = [
  { value: 'none', label: 'None (anonymous)' },
  { value: 'bearer', label: 'Bearer token' },
  { value: 'header', label: 'Custom header' },
  { value: 'oauth2', label: 'OAuth 2.1 access token' },
];

/** The collected form state for the MCP import source. */
export interface McpImportForm {
  endpointUrl: string;
  transport: McpTransport;
  name: string;
  /** Auth scheme; when `none` no credential is stored. */
  authType: McpAuthType;
  /** Bearer/OAuth2 token, or the header value for `header`. */
  authToken: string;
  /** Header name (only used when `authType === 'header'`). */
  authHeaderName: string;
}

/** A fresh, empty form with sensible defaults. */
export function emptyMcpImportForm(): McpImportForm {
  return {
    endpointUrl: '',
    transport: 'streamable_http',
    name: '',
    authType: 'none',
    authToken: '',
    authHeaderName: '',
  };
}

/**
 * Derive a friendly endpoint name from a URL's host when the user left the name blank.
 * Falls back to the trimmed raw URL (then "MCP Server") when it cannot be parsed.
 */
export function deriveEndpointNameFromUrl(url: string): string {
  const trimmed = (url ?? '').trim();
  if (!trimmed) return 'MCP Server';
  try {
    const host = new URL(trimmed).host;
    return host || trimmed;
  } catch {
    return trimmed;
  }
}

/** True when the transport speaks HTTP (and therefore needs a parseable http(s) URL). */
function isHttpTransport(transport: McpTransport): boolean {
  return transport === 'streamable_http' || transport === 'sse';
}

/**
 * Validate an MCP endpoint URL against its transport, mirroring apiome-rest's
 * `validate_mcp_endpoint_url` guards: the URL must be non-blank, and for an HTTP-family
 * transport (`streamable_http` / `sse`) it must parse as an `http(s)` URL. The `stdio`
 * transport's target is a local command, not a URL, so only the non-blank check applies.
 *
 * Shared by the import-source form and the endpoint-detail Settings tab so both surfaces
 * correct the user with the same rules before any network call.
 *
 * @param url       The raw endpoint URL (trimmed internally).
 * @param transport The selected transport.
 * @returns A human-readable error string, or `null` when the URL is acceptable.
 */
export function validateMcpEndpointUrl(url: string, transport: McpTransport): string | null {
  const trimmed = (url ?? '').trim();
  if (!trimmed) return 'Enter the MCP endpoint URL.';

  if (isHttpTransport(transport)) {
    let parsed: URL;
    try {
      parsed = new URL(trimmed);
    } catch {
      return 'Enter a valid URL (including http:// or https://).';
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return 'HTTP transports require an http:// or https:// URL.';
    }
  }

  return null;
}

/**
 * Validate the import form. Returns a human-readable error string, or `null` when the form is
 * ready to submit. Mirrors the server's guards (non-blank URL, http(s) for HTTP transports,
 * required secret fields per auth type) so the user is corrected before any network call.
 */
export function validateMcpImportForm(form: McpImportForm): string | null {
  const urlError = validateMcpEndpointUrl(form.endpointUrl, form.transport);
  if (urlError) return urlError;

  if (form.authType === 'bearer' || form.authType === 'oauth2') {
    if (!(form.authToken ?? '').trim()) return 'Enter the access token for the selected auth type.';
  }
  if (form.authType === 'header') {
    if (!(form.authHeaderName ?? '').trim()) return 'Enter the header name.';
    if (!(form.authToken ?? '').trim()) return 'Enter the header value.';
  }

  return null;
}

/** Request body for `POST /api/mcp/endpoints` (create the catalog endpoint). */
export interface McpCreateEndpointBody {
  name: string;
  endpoint_url: string;
  transport: McpTransport;
  visibility: 'private';
}

/** Build the create-endpoint body, defaulting the name from the URL host when blank. */
export function buildCreateEndpointBody(form: McpImportForm): McpCreateEndpointBody {
  const name = (form.name ?? '').trim() || deriveEndpointNameFromUrl(form.endpointUrl);
  return {
    name,
    endpoint_url: (form.endpointUrl ?? '').trim(),
    transport: form.transport,
    visibility: 'private',
  };
}

/** Request body for `PUT /api/mcp/endpoints/{id}/credentials`. */
export interface McpCredentialBody {
  auth_type: Exclude<McpAuthType, 'none'>;
  payload: Record<string, unknown>;
}

/**
 * Build the credential body for the selected auth type, or `null` when `authType === 'none'`
 * (anonymous — no credential is stored). The payload shape matches apiome-rest's
 * `validate_credential_payload` for each scheme.
 */
export function buildCredentialBody(form: McpImportForm): McpCredentialBody | null {
  switch (form.authType) {
    case 'bearer':
      return { auth_type: 'bearer', payload: { token: form.authToken.trim() } };
    case 'oauth2':
      return { auth_type: 'oauth2', payload: { access_token: form.authToken.trim() } };
    case 'header':
      return {
        auth_type: 'header',
        payload: { name: form.authHeaderName.trim(), value: form.authToken.trim() },
      };
    case 'none':
    default:
      return null;
  }
}

/** Per-kind capability tallies a successful discovery records on its result (`counts`). */
export interface McpDiscoveryCounts {
  tool?: number;
  resource?: number;
  resource_template?: number;
  prompt?: number;
  total?: number;
}

/** Wire shape of a discovery job (subset of apiome-rest `McpDiscoveryJobOut`). */
export interface McpDiscoveryJob {
  id: string;
  endpoint_id: string;
  state: string;
  trigger?: string;
  error?: string | null;
  result?: {
    version_id?: string;
    version_seq?: number;
    changed?: boolean;
    counts?: McpDiscoveryCounts;
  } & Record<string, unknown>;
}

/** Terminal job states (no further polling needed). */
export function isTerminalJobState(state: string | undefined | null): boolean {
  return state === 'completed' || state === 'failed';
}

/** True when the job finished successfully. */
export function isJobSuccess(job: McpDiscoveryJob | null | undefined): boolean {
  return !!job && job.state === 'completed';
}

/** Pull the produced version id from a finished job's result, if any. */
export function versionIdFromJob(job: McpDiscoveryJob | null | undefined): string | null {
  const vid = job?.result?.version_id;
  return typeof vid === 'string' && vid ? vid : null;
}

/**
 * Human-readable failure reason for a failed discovery job. Uses the job's classified error when
 * present, otherwise a generic message. This is what the import flow shows before offering the user
 * the choice to discard the endpoint or add it anyway.
 */
export function discoveryFailureMessage(job: McpDiscoveryJob | null | undefined): string {
  const err = job?.error;
  return typeof err === 'string' && err.trim() ? err : 'The MCP server could not be discovered.';
}

/** Pluralize `count noun`, e.g. (3, 'tool') → "3 tools", (1, 'tool') → "1 tool". */
function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/**
 * A short, human-readable summary of what a successful discovery found — the per-kind
 * capability tallies the job recorded in `result.counts`. Only non-zero kinds are listed,
 * joined with a middot, e.g. "3 tools · 2 resources · 1 prompt". Returns:
 *   - `null` when the job carried no counts (older runs / nothing to summarize), so callers
 *      can omit the summary line entirely.
 *   - "No capabilities found" when the server was reached but exposed nothing.
 * The labels mirror the catalog's capability kinds (tool / resource / template / prompt).
 */
export function discoverySummary(job: McpDiscoveryJob | null | undefined): string | null {
  const counts = job?.result?.counts;
  if (!counts) return null;

  const parts: string[] = [];
  if (counts.tool) parts.push(pluralize(counts.tool, 'tool'));
  if (counts.resource) parts.push(pluralize(counts.resource, 'resource'));
  if (counts.resource_template) parts.push(pluralize(counts.resource_template, 'resource template'));
  if (counts.prompt) parts.push(pluralize(counts.prompt, 'prompt'));

  if (parts.length === 0) return 'No capabilities found';
  return parts.join(' · ');
}

/** Human-readable label for a discovery job state (for the live status line). */
export function discoveryStatusLabel(state: string | undefined | null): string {
  switch (state) {
    case 'queued':
      return 'Queued…';
    case 'running':
      return 'Discovering capabilities…';
    case 'completed':
      return 'Discovery complete';
    case 'failed':
      return 'Discovery failed';
    default:
      return 'Starting discovery…';
  }
}
