/**
 * Toolset-disable impact helpers — MTG-4.5 (#4784).
 */

import {
  findActiveKeysEffectivelyEnablingTools,
  formatToolsetDisableImpactMessage,
  isToolEffectivelyEnabledForKey,
  toolInCeilingFromPolicy,
  toolInDefaultEnableSetFromPolicy,
} from '../src/app/ade/dashboard/tenants/mcpToolsetDisableImpact';
import type { McpPolicyFormState } from '../src/app/ade/dashboard/tenants/mcpPolicyForm';
import type { McpApiKeyMetadata } from '../src/app/ade/dashboard/tenants/mcpKeysApi';

function policy(overrides: Partial<McpPolicyFormState> = {}): McpPolicyFormState {
  return {
    default_mode: 'explicit',
    allow_anonymous_mcp: true,
    tools: [
      {
        tool_id: 'ping',
        description: 'Health',
        toolset: 'health',
        in_ceiling: true,
        default_enabled: true,
        anonymous_enabled: true,
      },
      {
        tool_id: 'spec.search',
        description: 'Search',
        toolset: 'search',
        in_ceiling: true,
        default_enabled: false,
        anonymous_enabled: true,
      },
      {
        tool_id: 'spec.list',
        description: 'List',
        toolset: 'catalog',
        in_ceiling: false,
        default_enabled: false,
        anonymous_enabled: true,
      },
    ],
    ...overrides,
  };
}

function key(partial: Partial<McpApiKeyMetadata> & Pick<McpApiKeyMetadata, 'id' | 'prefix'>): McpApiKeyMetadata {
  return {
    label: partial.label ?? 'Key',
    scope_json: { tenants: [], projects: [] },
    capability_mode: 'inherit',
    created_at: '2026-01-01T00:00:00Z',
    ...partial,
  };
}

describe('mcpToolsetDisableImpact', () => {
  it('toolInCeilingFromPolicy respects default_mode all / inherit / explicit', () => {
    expect(toolInCeilingFromPolicy('spec.list', policy({ default_mode: 'all' }))).toBe(true);
    expect(
      toolInCeilingFromPolicy(
        'spec.list',
        policy({ default_mode: 'inherit_registry' }),
      ),
    ).toBe(false);
    expect(toolInCeilingFromPolicy('spec.list', policy({ default_mode: 'explicit' }))).toBe(
      false,
    );
    expect(toolInCeilingFromPolicy('ping', policy({ default_mode: 'explicit' }))).toBe(true);
  });

  it('toolInDefaultEnableSetFromPolicy follows default_enabled + mode', () => {
    expect(toolInDefaultEnableSetFromPolicy('ping', policy())).toBe(true);
    expect(toolInDefaultEnableSetFromPolicy('spec.search', policy())).toBe(false);
    expect(
      toolInDefaultEnableSetFromPolicy('ping', policy({ default_mode: 'all' })),
    ).toBe(true);
  });

  it('isToolEffectivelyEnabledForKey ANDs ceiling with inherit/explicit grants', () => {
    const p = policy();
    const inherit = key({ id: '1', prefix: 'mcp_aa', capability_mode: 'inherit' });
    expect(isToolEffectivelyEnabledForKey('ping', inherit, p)).toBe(true);
    expect(isToolEffectivelyEnabledForKey('spec.search', inherit, p)).toBe(false);

    const explicit = key({
      id: '2',
      prefix: 'mcp_bb',
      capability_mode: 'explicit',
      enabled_tools: ['spec.search'],
    });
    expect(isToolEffectivelyEnabledForKey('spec.search', explicit, p)).toBe(true);
    expect(isToolEffectivelyEnabledForKey('ping', explicit, p)).toBe(false);

    const overCeiling = key({
      id: '3',
      prefix: 'mcp_cc',
      capability_mode: 'explicit',
      enabled_tools: ['spec.list'],
    });
    expect(isToolEffectivelyEnabledForKey('spec.list', overCeiling, p)).toBe(false);
  });

  it('findActiveKeysEffectivelyEnablingTools skips revoked and untouched keys', () => {
    const p = policy();
    const keys = [
      key({ id: 'a', prefix: 'mcp_aa', label: 'Prod', capability_mode: 'inherit' }),
      key({
        id: 'b',
        prefix: 'mcp_bb',
        label: 'Search only',
        capability_mode: 'explicit',
        enabled_tools: ['spec.search'],
      }),
      key({
        id: 'c',
        prefix: 'mcp_cc',
        label: 'Revoked',
        capability_mode: 'inherit',
        revoked_at: '2026-02-01T00:00:00Z',
      }),
      key({
        id: 'd',
        prefix: 'mcp_dd',
        label: 'Explicit empty',
        capability_mode: 'explicit',
        enabled_tools: [],
      }),
    ];

    const health = findActiveKeysEffectivelyEnablingTools(p, ['ping'], keys);
    expect(health.map((k) => k.prefix)).toEqual(['mcp_aa']);

    const search = findActiveKeysEffectivelyEnablingTools(p, ['spec.search'], keys);
    expect(search.map((k) => k.prefix)).toEqual(['mcp_bb']);
  });

  it('formatToolsetDisableImpactMessage summarizes count and prefixes', () => {
    const msg = formatToolsetDisableImpactMessage('search', [
      { id: '1', prefix: 'mcp_aa', label: 'A' },
      { id: '2', prefix: 'mcp_bb', label: 'B' },
    ]);
    expect(msg).toContain('search toolset');
    expect(msg).toContain('2 active MCP keys');
    expect(msg).toContain('mcp_aa…');
    expect(msg).toContain('mcp_bb…');
    expect(msg).not.toContain('secret');
  });
});
