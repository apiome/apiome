/**
 * Client helpers for tenant MCP API keys + capabilities (MTG-4.3 / #4782).
 *
 * Talks to `/api/tenants/mcp-keys` proxies, which forward to MTG-3.2 / MTG-3.3
 * REST. Types mirror REST snake_case. List metadata uses `capability_mode`;
 * PUT/preview bodies use `mode`.
 */

export type McpKeyCapabilityMode = 'inherit' | 'explicit';

export interface McpKeyScopeJson {
  tenants: string[];
  projects: string[];
}

export interface McpApiKeyMetadata {
  id: string;
  prefix: string;
  label: string;
  scope_json: McpKeyScopeJson;
  capability_mode: McpKeyCapabilityMode;
  enabled_tools?: string[];
  created_at: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  last_used_at?: string | null;
  created_by?: string | null;
}

export interface McpApiKeyListResponse {
  keys: McpApiKeyMetadata[];
}

export interface McpKeyCapabilitiesRequest {
  mode: McpKeyCapabilityMode;
  enabled_tools?: string[] | null;
}

export interface McpKeyCapabilitiesResponse {
  mode: McpKeyCapabilityMode;
  enabled_tools: string[];
}

export interface McpKeyEffectiveToolRow {
  tool_id: string;
  enabled: boolean;
  deny_reason?: string | null;
}

export interface McpKeyCapabilitiesPreviewResponse {
  tools: McpKeyEffectiveToolRow[];
}

async function readProxyJson<T>(res: Response): Promise<T> {
  const json = await res.json();
  if (!json.success) {
    const err = json.error;
    const message =
      typeof err === 'object' && err !== null
        ? (err as { message?: string }).message || 'Request failed'
        : err || 'Request failed';
    throw new Error(message);
  }
  return json.data as T;
}

/** List MCP API keys for the current tenant (includes revoked for audit). */
export async function fetchMcpKeys(): Promise<McpApiKeyListResponse> {
  const res = await fetch('/api/tenants/mcp-keys', { cache: 'no-store' });
  return readProxyJson<McpApiKeyListResponse>(res);
}

/** Persist inherit/explicit capabilities for one MCP key. */
export async function putMcpKeyCapabilities(
  keyId: string,
  body: McpKeyCapabilitiesRequest,
): Promise<McpKeyCapabilitiesResponse> {
  const res = await fetch(
    `/api/tenants/mcp-keys/${encodeURIComponent(keyId)}/capabilities`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  return readProxyJson<McpKeyCapabilitiesResponse>(res);
}

/** Dry-run effective enable-set for the given mode/enabled_tools. */
export async function previewMcpKeyCapabilities(
  keyId: string,
  body: McpKeyCapabilitiesRequest,
): Promise<McpKeyCapabilitiesPreviewResponse> {
  const res = await fetch(
    `/api/tenants/mcp-keys/${encodeURIComponent(keyId)}/capabilities/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  return readProxyJson<McpKeyCapabilitiesPreviewResponse>(res);
}
