/**
 * Unit tests for MCP policy before/after diff helpers (MTG-5.2 / #4786).
 */

import { describe, expect, it } from '@jest/globals';
import {
  diffMcpPolicySnapshots,
  formatToolFlagValue,
  type McpPolicyAuditSnapshot,
} from '../src/app/ade/dashboard/tenants/mcpPolicyHistoryDiff';

const base = (): McpPolicyAuditSnapshot => ({
  default_mode: 'all',
  allow_anonymous_mcp: true,
  tools: [
    {
      tool_id: 'ping',
      in_ceiling: true,
      default_enabled: true,
      anonymous_enabled: true,
    },
  ],
});

describe('diffMcpPolicySnapshots', () => {
  it('returns empty diff when snapshots match', () => {
    const snap = base();
    const diff = diffMcpPolicySnapshots(snap, snap);
    expect(diff.topLevel).toEqual([]);
    expect(diff.tools).toEqual([]);
    expect(diff.summary).toBe('No visible changes');
  });

  it('detects top-level default_mode and anonymous kill switch', () => {
    const before = base();
    const after: McpPolicyAuditSnapshot = {
      ...before,
      default_mode: 'explicit',
      allow_anonymous_mcp: false,
    };
    const diff = diffMcpPolicySnapshots(before, after);
    expect(diff.topLevel).toEqual([
      {
        field: 'default_mode',
        label: 'Default mode',
        before: 'all',
        after: 'explicit',
      },
      {
        field: 'allow_anonymous_mcp',
        label: 'Allow anonymous MCP',
        before: 'on',
        after: 'off',
      },
    ]);
    expect(diff.summary).toContain('default mode');
    expect(diff.summary).toContain('allow anonymous mcp');
  });

  it('emits per-tool flag before/after for enablement changes', () => {
    const before = base();
    const after: McpPolicyAuditSnapshot = {
      ...before,
      tools: [
        {
          tool_id: 'ping',
          in_ceiling: true,
          default_enabled: false,
          anonymous_enabled: false,
        },
      ],
    };
    const diff = diffMcpPolicySnapshots(before, after);
    expect(diff.tools).toEqual([
      {
        tool_id: 'ping',
        flag: 'default_enabled',
        label: 'Default',
        before: true,
        after: false,
      },
      {
        tool_id: 'ping',
        flag: 'anonymous_enabled',
        label: 'Anonymous',
        before: true,
        after: false,
      },
    ]);
    expect(diff.summary).toBe('2 tool flags');
  });

  it('treats added/removed tools as null↔bool flag changes', () => {
    const before: McpPolicyAuditSnapshot = {
      default_mode: 'explicit',
      allow_anonymous_mcp: true,
      tools: [],
    };
    const after: McpPolicyAuditSnapshot = {
      default_mode: 'explicit',
      allow_anonymous_mcp: true,
      tools: [
        {
          tool_id: 'spec.list',
          in_ceiling: true,
          default_enabled: true,
          anonymous_enabled: true,
        },
      ],
    };
    const diff = diffMcpPolicySnapshots(before, after);
    expect(diff.tools).toHaveLength(3);
    expect(diff.tools.every((t) => t.tool_id === 'spec.list' && t.before === null)).toBe(
      true,
    );
    expect(diff.tools.every((t) => t.after === true)).toBe(true);
  });
});

describe('formatToolFlagValue', () => {
  it('maps booleans and null', () => {
    expect(formatToolFlagValue(true)).toBe('on');
    expect(formatToolFlagValue(false)).toBe('off');
    expect(formatToolFlagValue(null)).toBe('—');
  });
});
