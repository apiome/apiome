/**
 * Client helpers for tenant MCP policy (MTG-4.1 / #4780).
 *
 * Talks to the `/api/tenants/mcp-policy` and `/api/api-keys/mcp-tools` proxies,
 * which forward to MTG-3.1 / MTG-1.1 REST endpoints. Types mirror REST snake_case.
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

/** Load the MTG-1.1 MCP tool catalog for admin labels / rows. */
export async function fetchMcpToolCatalog(): Promise<McpToolCatalogResponse> {
  const res = await fetch('/api/api-keys/mcp-tools', { cache: 'no-store' });
  return readProxyJson<McpToolCatalogResponse>(res);
}
