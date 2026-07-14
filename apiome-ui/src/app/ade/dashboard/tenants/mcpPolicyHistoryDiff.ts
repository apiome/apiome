/**
 * Pure before/after diff for tenant MCP policy audit snapshots (MTG-5.2 / #4786).
 */

export interface McpPolicyAuditTool {
  tool_id: string;
  in_ceiling: boolean;
  default_enabled: boolean;
  anonymous_enabled: boolean;
}

export interface McpPolicyAuditSnapshot {
  default_mode: string;
  allow_anonymous_mcp: boolean;
  tools: McpPolicyAuditTool[];
}

export interface McpPolicyTopLevelChange {
  field: 'default_mode' | 'allow_anonymous_mcp';
  label: string;
  before: string;
  after: string;
}

export interface McpPolicyToolFlagChange {
  tool_id: string;
  flag: 'in_ceiling' | 'default_enabled' | 'anonymous_enabled';
  label: string;
  before: boolean | null;
  after: boolean | null;
}

export interface McpPolicySnapshotDiff {
  topLevel: McpPolicyTopLevelChange[];
  tools: McpPolicyToolFlagChange[];
  /** Short list-row blurb, e.g. "default mode · 2 tool flags". */
  summary: string;
}

const FLAG_LABELS: Record<McpPolicyToolFlagChange['flag'], string> = {
  in_ceiling: 'Ceiling',
  default_enabled: 'Default',
  anonymous_enabled: 'Anonymous',
};

function boolLabel(value: boolean | null): string {
  if (value === null) return '—';
  return value ? 'on' : 'off';
}

function normalizeTool(raw: Partial<McpPolicyAuditTool> | undefined): McpPolicyAuditTool | null {
  if (!raw?.tool_id) return null;
  return {
    tool_id: String(raw.tool_id),
    in_ceiling: Boolean(raw.in_ceiling),
    default_enabled: Boolean(raw.default_enabled),
    anonymous_enabled: Boolean(raw.anonymous_enabled ?? true),
  };
}

function toolMap(tools: McpPolicyAuditTool[]): Map<string, McpPolicyAuditTool> {
  const map = new Map<string, McpPolicyAuditTool>();
  for (const tool of tools) {
    const n = normalizeTool(tool);
    if (n) map.set(n.tool_id, n);
  }
  return map;
}

/** Compare two policy audit snapshots; only changed fields/tools are returned. */
export function diffMcpPolicySnapshots(
  before: McpPolicyAuditSnapshot,
  after: McpPolicyAuditSnapshot,
): McpPolicySnapshotDiff {
  const topLevel: McpPolicyTopLevelChange[] = [];
  if (before.default_mode !== after.default_mode) {
    topLevel.push({
      field: 'default_mode',
      label: 'Default mode',
      before: String(before.default_mode),
      after: String(after.default_mode),
    });
  }
  if (Boolean(before.allow_anonymous_mcp) !== Boolean(after.allow_anonymous_mcp)) {
    topLevel.push({
      field: 'allow_anonymous_mcp',
      label: 'Allow anonymous MCP',
      before: boolLabel(Boolean(before.allow_anonymous_mcp)),
      after: boolLabel(Boolean(after.allow_anonymous_mcp)),
    });
  }

  const beforeTools = toolMap(before.tools ?? []);
  const afterTools = toolMap(after.tools ?? []);
  const toolIds = Array.from(
    new Set([...beforeTools.keys(), ...afterTools.keys()]),
  ).sort();

  const tools: McpPolicyToolFlagChange[] = [];
  for (const toolId of toolIds) {
    const b = beforeTools.get(toolId) ?? null;
    const a = afterTools.get(toolId) ?? null;
    for (const flag of ['in_ceiling', 'default_enabled', 'anonymous_enabled'] as const) {
      const beforeVal = b ? b[flag] : null;
      const afterVal = a ? a[flag] : null;
      if (beforeVal === afterVal) continue;
      tools.push({
        tool_id: toolId,
        flag,
        label: FLAG_LABELS[flag],
        before: beforeVal,
        after: afterVal,
      });
    }
  }

  const parts: string[] = [];
  for (const change of topLevel) {
    parts.push(change.label.toLowerCase());
  }
  if (tools.length === 1) parts.push('1 tool flag');
  else if (tools.length > 1) parts.push(`${tools.length} tool flags`);

  const summary = parts.length > 0 ? parts.join(' · ') : 'No visible changes';

  return { topLevel, tools, summary };
}

/** Format a boolean/null tool flag for display. */
export function formatToolFlagValue(value: boolean | null): string {
  return boolLabel(value);
}
