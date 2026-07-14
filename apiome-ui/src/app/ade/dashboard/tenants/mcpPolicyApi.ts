/**
 * Client helpers for tenant MCP policy (MTG-4.1 / #4780, MTG-5.1 / #4785,
 * MTG-5.2 / #4786 history).
 *
 * Talks to the `/api/tenants/mcp-policy`, `/api/tenants/mcp-policy/history`,
 * `/api/api-keys/mcp-tools`, and `/api/api-keys/mcp-capability-presets`
 * proxies. Types mirror REST snake_case.
 */

export type TenantDefaultMode = 'all' | 'inherit_registry' | 'explicit';

export interface TenantMcpPolicyTool {
  tool_id: string;
  in_ceiling: boolean;
  default_enabled: boolean;
  anonymous_enabled: boolean;
}

export interface TenantMcpPolicyResponse {
  default_mode: TenantDefaultMode;
  allow_anonymous_mcp: boolean;
  tools: TenantMcpPolicyTool[];
  updated_at: string | null;
  updated_by: string | null;
}

export interface TenantMcpPolicyPutRequest {
  default_mode: TenantDefaultMode;
  allow_anonymous_mcp: boolean;
  tools: TenantMcpPolicyTool[];
}

export interface McpToolCatalogItem {
  id: string;
  description: string;
  toolset: string;
}

export interface McpToolCatalogResponse {
  tools: McpToolCatalogItem[];
}

export interface TenantMcpPolicySnapshot {
  default_mode: TenantDefaultMode;
  allow_anonymous_mcp: boolean;
  tools: TenantMcpPolicyTool[];
}

export interface TenantMcpPolicyChangeEntry {
  id: string;
  actor_user_id: string | null;
  actor_label: string | null;
  created_at: string;
  before_policy: TenantMcpPolicySnapshot;
  after_policy: TenantMcpPolicySnapshot;
}

export interface TenantMcpPolicyHistoryResponse {
  changes: TenantMcpPolicyChangeEntry[];
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

/** Load the current tenant's MCP governance policy. */
export async function fetchMcpPolicy(): Promise<TenantMcpPolicyResponse> {
  const res = await fetch('/api/tenants/mcp-policy', { cache: 'no-store' });
  return readProxyJson<TenantMcpPolicyResponse>(res);
}

/** Replace the current tenant's MCP governance policy (full PUT). */
export async function putMcpPolicy(
  body: TenantMcpPolicyPutRequest,
): Promise<TenantMcpPolicyResponse> {
  const res = await fetch('/api/tenants/mcp-policy', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readProxyJson<TenantMcpPolicyResponse>(res);
}

/** Load newest-first MCP policy change audit history (MTG-5.2). */
export async function fetchMcpPolicyHistory(
  limit = 50,
): Promise<TenantMcpPolicyHistoryResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`/api/tenants/mcp-policy/history?${qs}`, {
    cache: 'no-store',
  });
  return readProxyJson<TenantMcpPolicyHistoryResponse>(res);
}

/** Load the MTG-1.1 MCP tool catalog for admin labels / rows. */
export async function fetchMcpToolCatalog(): Promise<McpToolCatalogResponse> {
  const res = await fetch('/api/api-keys/mcp-tools', { cache: 'no-store' });
  return readProxyJson<McpToolCatalogResponse>(res);
}

export interface McpCapabilityPresetItem {
  id: string;
  label: string;
  toolsets: string[];
}

export interface McpCapabilityPresetsResponse {
  presets: McpCapabilityPresetItem[];
}

/** Load named MCP capability presets (MTG-5.1 documented matrix). */
export async function fetchMcpCapabilityPresets(): Promise<McpCapabilityPresetsResponse> {
  const res = await fetch('/api/api-keys/mcp-capability-presets', { cache: 'no-store' });
  return readProxyJson<McpCapabilityPresetsResponse>(res);
}
