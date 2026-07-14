/**
 * Client-side impact helpers for MTG-4.5 (#4784) toolset disable confirm.
 *
 * Mirrors MTG-1.4 (`app.mcp_effective_policy`) so the Tenants UI can warn
 * when turning off a toolset that active keys currently effective-enable,
 * without round-tripping every key's capabilities/preview endpoint.
 */

import type { McpApiKeyMetadata } from './mcpKeysApi';
import type { McpPolicyFormState, McpPolicyToolRow } from './mcpPolicyForm';

export interface ImpactedMcpKey {
  id: string;
  prefix: string;
  label: string;
}

function toolRowMap(policy: McpPolicyFormState): Map<string, McpPolicyToolRow> {
  return new Map(policy.tools.map((row) => [row.tool_id, row]));
}

/**
 * Whether `toolId` is in the tenant ceiling under the saved policy's
 * `default_mode` (same rules as MTG-1.4 `tool_in_ceiling`).
 */
export function toolInCeilingFromPolicy(
  toolId: string,
  policy: McpPolicyFormState,
): boolean {
  const row = toolRowMap(policy).get(toolId);
  if (policy.default_mode === 'all') return true;
  if (policy.default_mode === 'inherit_registry') {
    return row ? row.in_ceiling : true;
  }
  return row ? row.in_ceiling : false;
}

/**
 * Whether `toolId` is in the tenant default enable-set (MTG-1.4
 * `tool_in_default_enable_set`). Does not re-check ceiling.
 */
export function toolInDefaultEnableSetFromPolicy(
  toolId: string,
  policy: McpPolicyFormState,
): boolean {
  const row = toolRowMap(policy).get(toolId);
  if (policy.default_mode === 'all') return true;
  if (policy.default_mode === 'inherit_registry') {
    return row ? row.default_enabled : true;
  }
  return row ? row.default_enabled : false;
}

/**
 * Whether `toolId` is effectively enabled for `key` under `policy`
 * (MTG-1.4 `is_tool_effectively_enabled` without a separate registry set —
 * callers only pass catalog tool ids).
 */
export function isToolEffectivelyEnabledForKey(
  toolId: string,
  key: Pick<McpApiKeyMetadata, 'capability_mode' | 'enabled_tools'>,
  policy: McpPolicyFormState,
): boolean {
  if (!toolInCeilingFromPolicy(toolId, policy)) return false;
  if (key.capability_mode === 'inherit') {
    return toolInDefaultEnableSetFromPolicy(toolId, policy);
  }
  if (key.capability_mode === 'explicit') {
    return (key.enabled_tools ?? []).includes(toolId);
  }
  return false;
}

/**
 * Active (non-revoked) MCP keys that currently effective-enable at least one
 * tool in `toolIds` under the saved tenant policy.
 */
export function findActiveKeysEffectivelyEnablingTools(
  policy: McpPolicyFormState,
  toolIds: readonly string[],
  keys: readonly McpApiKeyMetadata[],
): ImpactedMcpKey[] {
  if (toolIds.length === 0) return [];
  const active = keys.filter((k) => !k.revoked_at);
  const impacted: ImpactedMcpKey[] = [];
  for (const key of active) {
    const hits = toolIds.some((id) => isToolEffectivelyEnabledForKey(id, key, policy));
    if (hits) {
      impacted.push({ id: key.id, prefix: key.prefix, label: key.label });
    }
  }
  return impacted;
}

/** Short confirm copy summarizing impacted key count + prefixes (not secrets). */
export function formatToolsetDisableImpactMessage(
  toolset: string,
  impacted: readonly ImpactedMcpKey[],
): string {
  const count = impacted.length;
  const prefixes = impacted.map((k) => `${k.prefix}…`).join(', ');
  const keyWord = count === 1 ? 'key' : 'keys';
  return (
    `Disabling the ${toolset} toolset will remove effective access for ` +
    `${count} active MCP ${keyWord}: ${prefixes}. ` +
    `Agents using ${count === 1 ? 'that key' : 'those keys'} will lose those ` +
    `tools on the next call. Continue?`
  );
}
