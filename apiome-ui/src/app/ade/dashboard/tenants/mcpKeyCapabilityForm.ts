/**
 * Pure helpers for the per-key MCP capability editor (MTG-4.3 / #4782).
 *
 * Custom (explicit) enablesets are constrained by the saved tenant ceiling.
 * Inherit clears the explicit list on persist.
 */

import type { McpToolCatalogItem } from './mcpPolicyApi';
import { MCP_TOOLSET_ORDER, type ToolsetToggleState } from './mcpPolicyForm';
import type {
  McpKeyCapabilitiesRequest,
  McpKeyCapabilityMode,
} from './mcpKeysApi';

export interface McpKeyCapabilityToolRow {
  tool_id: string;
  description: string;
  toolset: string;
  /** From saved tenant policy; unlocked tools cannot be enabled. */
  in_ceiling: boolean;
  /** In the key's explicit enable-set (ignored when mode is inherit). */
  enabled: boolean;
}

export interface McpKeyCapabilityFormState {
  mode: McpKeyCapabilityMode;
  tools: McpKeyCapabilityToolRow[];
}

export interface McpKeyToolsetGroup {
  toolset: string;
  tools: McpKeyCapabilityToolRow[];
  /** Enable state among ceiling (unlocked) tools only. */
  enableState: ToolsetToggleState;
  unlockedCount: number;
  enabledUnlockedCount: number;
}

/**
 * Build editor rows from catalog + saved ceiling tool ids + current grant.
 * Tools not in the ceiling stay locked off (enabled forced false).
 */
export function mcpKeyCapabilityFormFromSources(
  mode: McpKeyCapabilityMode,
  enabledTools: string[],
  catalog: McpToolCatalogItem[],
  ceilingToolIds: Iterable<string>,
): McpKeyCapabilityFormState {
  const ceiling = new Set(ceilingToolIds);
  const enableSet = new Set(enabledTools);
  const tools: McpKeyCapabilityToolRow[] = catalog.map((item) => {
    const inCeiling = ceiling.has(item.id);
    const wantEnabled = mode === 'explicit' && enableSet.has(item.id);
    return {
      tool_id: item.id,
      description: item.description,
      toolset: item.toolset,
      in_ceiling: inCeiling,
      enabled: inCeiling && wantEnabled,
    };
  });
  return { mode, tools };
}

/** PUT body for MTG-3.3. Inherit omits/clears the list; explicit sends ⊆ ceiling. */
export function buildMcpKeyCapabilitiesPutBody(
  form: McpKeyCapabilityFormState,
): McpKeyCapabilitiesRequest {
  if (form.mode === 'inherit') {
    return { mode: 'inherit' };
  }
  const enabled_tools = form.tools
    .filter((row) => row.enabled && row.in_ceiling)
    .map((row) => row.tool_id);
  return { mode: 'explicit', enabled_tools };
}

/**
 * Client-side guard matching REST ceiling: explicit enablesets must be ⊆ ceiling.
 * Returns an error message or null when valid.
 */
export function validateMcpKeyCapabilityForm(
  form: McpKeyCapabilityFormState,
): string | null {
  if (form.mode === 'inherit') return null;
  const offenders = form.tools
    .filter((row) => row.enabled && !row.in_ceiling)
    .map((row) => row.tool_id);
  if (offenders.length > 0) {
    return `Enable-set exceeds tenant ceiling: ${offenders.join(', ')}`;
  }
  return null;
}

export function hasMcpKeyCapabilityChanges(
  current: McpKeyCapabilityFormState,
  baseline: McpKeyCapabilityFormState,
): boolean {
  if (current.mode !== baseline.mode) return true;
  if (current.mode === 'inherit') return false;
  const currentIds = current.tools
    .filter((t) => t.enabled)
    .map((t) => t.tool_id)
    .sort()
    .join('\0');
  const baselineIds = baseline.tools
    .filter((t) => t.enabled)
    .map((t) => t.tool_id)
    .sort()
    .join('\0');
  return currentIds !== baselineIds;
}

function enableStateForUnlocked(tools: McpKeyCapabilityToolRow[]): ToolsetToggleState {
  const unlocked = tools.filter((t) => t.in_ceiling);
  if (unlocked.length === 0) return 'none';
  const enabled = unlocked.filter((t) => t.enabled).length;
  if (enabled === 0) return 'none';
  if (enabled === unlocked.length) return 'all';
  return 'mixed';
}

/** Group capability rows by toolset (same MTG-1.1 order as tenant policy). */
export function groupKeyToolsByToolset(
  tools: McpKeyCapabilityToolRow[],
): McpKeyToolsetGroup[] {
  const bySet = new Map<string, McpKeyCapabilityToolRow[]>();
  for (const tool of tools) {
    const key = tool.toolset || 'other';
    const list = bySet.get(key);
    if (list) list.push(tool);
    else bySet.set(key, [tool]);
  }

  const known = new Set<string>(MCP_TOOLSET_ORDER);
  const ordered: string[] = [
    ...MCP_TOOLSET_ORDER.filter((name) => bySet.has(name)),
    ...[...bySet.keys()].filter((name) => !known.has(name)).sort(),
  ];

  return ordered.map((toolset) => {
    const groupTools = bySet.get(toolset) ?? [];
    const unlocked = groupTools.filter((t) => t.in_ceiling);
    return {
      toolset,
      tools: groupTools,
      enableState: enableStateForUnlocked(groupTools),
      unlockedCount: unlocked.length,
      enabledUnlockedCount: unlocked.filter((t) => t.enabled).length,
    };
  });
}

/**
 * Master toolset switch for custom mode. Only mutates ceiling tools;
 * locked tools stay enabled=false.
 */
export function patchKeyToolsetEnabled(
  form: McpKeyCapabilityFormState,
  toolset: string,
  enabled: boolean,
): McpKeyCapabilityFormState {
  return {
    ...form,
    tools: form.tools.map((row) => {
      if (row.toolset !== toolset) return row;
      if (!row.in_ceiling) return { ...row, enabled: false };
      return { ...row, enabled };
    }),
  };
}

/** Toggle a single tool; no-op for tools outside the ceiling. */
export function patchKeyToolEnabled(
  form: McpKeyCapabilityFormState,
  toolId: string,
  enabled: boolean,
): McpKeyCapabilityFormState {
  return {
    ...form,
    tools: form.tools.map((row) => {
      if (row.tool_id !== toolId) return row;
      if (!row.in_ceiling) return { ...row, enabled: false };
      return { ...row, enabled };
    }),
  };
}

/** Switch mode; when entering inherit, enabled flags are cleared visually. */
export function setKeyCapabilityMode(
  form: McpKeyCapabilityFormState,
  mode: McpKeyCapabilityMode,
): McpKeyCapabilityFormState {
  if (mode === 'inherit') {
    return {
      mode,
      tools: form.tools.map((row) => ({ ...row, enabled: false })),
    };
  }
  return { ...form, mode };
}
