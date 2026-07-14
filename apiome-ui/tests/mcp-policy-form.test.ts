/**
 * Tenant MCP policy form helpers — MTG-4.1 (#4780).
 */

import {
  buildMcpPolicyPutBody,
  defaultFlagsForMode,
  hasMcpPolicyChanges,
  mcpPolicyFormFromSources,
  patchToolFlag,
  validateMcpPolicyForm,
  type McpPolicyFormState,
} from '../src/app/ade/dashboard/tenants/mcpPolicyForm';
import type {
  McpToolCatalogItem,
  TenantMcpPolicyResponse,
} from '../src/app/ade/dashboard/tenants/mcpPolicyApi';

const CATALOG: McpToolCatalogItem[] = [
  { id: 'ping', description: 'Health check', toolset: 'health' },
  { id: 'spec.list', description: 'List specs', toolset: 'catalog' },
];

function policy(overrides: Partial<TenantMcpPolicyResponse> = {}): TenantMcpPolicyResponse {
  return {
    default_mode: 'all',
    allow_anonymous_mcp: true,
    tools: [],
    updated_at: null,
    updated_by: null,
    ...overrides,
  };
}

function form(overrides: Partial<McpPolicyFormState> = {}): McpPolicyFormState {
  return {
    ...mcpPolicyFormFromSources(policy(), CATALOG),
    ...overrides,
  };
}

describe('defaultFlagsForMode', () => {
  it('treats all and inherit_registry as fully enabled defaults', () => {
    expect(defaultFlagsForMode('all')).toEqual({
      in_ceiling: true,
      default_enabled: true,
      anonymous_enabled: true,
    });
    expect(defaultFlagsForMode('inherit_registry')).toEqual({
      in_ceiling: true,
      default_enabled: true,
      anonymous_enabled: true,
    });
  });

  it('treats explicit missing rows as out of ceiling', () => {
    expect(defaultFlagsForMode('explicit')).toEqual({
      in_ceiling: false,
      default_enabled: false,
      anonymous_enabled: true,
    });
  });
});

describe('mcpPolicyFormFromSources', () => {
  it('fills missing rows from default_mode when policy tools are empty', () => {
    const f = mcpPolicyFormFromSources(policy({ default_mode: 'explicit' }), CATALOG);
    expect(f.tools).toHaveLength(2);
    expect(f.tools[0]).toMatchObject({
      tool_id: 'ping',
      in_ceiling: false,
      default_enabled: false,
      anonymous_enabled: true,
    });
    expect(f.tools[1].tool_id).toBe('spec.list');
  });

  it('prefers stored policy rows over defaults', () => {
    const f = mcpPolicyFormFromSources(
      policy({
        default_mode: 'explicit',
        tools: [
          {
            tool_id: 'ping',
            in_ceiling: true,
            default_enabled: true,
            anonymous_enabled: false,
          },
        ],
      }),
      CATALOG,
    );
    expect(f.tools[0]).toMatchObject({
      tool_id: 'ping',
      in_ceiling: true,
      default_enabled: true,
      anonymous_enabled: false,
      description: 'Health check',
      toolset: 'health',
    });
    expect(f.tools[1]).toMatchObject({
      tool_id: 'spec.list',
      in_ceiling: false,
      default_enabled: false,
    });
  });
});

describe('validateMcpPolicyForm', () => {
  it('accepts a valid form', () => {
    expect(validateMcpPolicyForm(form())).toBeNull();
  });

  it('rejects default_enabled without in_ceiling', () => {
    const bad = form({
      tools: [
        {
          tool_id: 'ping',
          description: 'Health check',
          toolset: 'health',
          in_ceiling: false,
          default_enabled: true,
          anonymous_enabled: true,
        },
      ],
    });
    expect(validateMcpPolicyForm(bad)).toMatch(/default_enabled requires in_ceiling/);
  });

  it('rejects duplicate tool ids', () => {
    const row = {
      tool_id: 'ping',
      description: 'Health check',
      toolset: 'health',
      in_ceiling: true,
      default_enabled: true,
      anonymous_enabled: true,
    };
    expect(validateMcpPolicyForm(form({ tools: [row, { ...row }] }))).toMatch(/Duplicate/);
  });
});

describe('buildMcpPolicyPutBody / hasMcpPolicyChanges / patchToolFlag', () => {
  it('builds a full replace-all PUT body', () => {
    const f = mcpPolicyFormFromSources(
      policy({
        default_mode: 'inherit_registry',
        allow_anonymous_mcp: false,
      }),
      CATALOG,
    );
    expect(buildMcpPolicyPutBody(f)).toEqual({
      default_mode: 'inherit_registry',
      allow_anonymous_mcp: false,
      tools: [
        {
          tool_id: 'ping',
          in_ceiling: true,
          default_enabled: true,
          anonymous_enabled: true,
        },
        {
          tool_id: 'spec.list',
          in_ceiling: true,
          default_enabled: true,
          anonymous_enabled: true,
        },
      ],
    });
  });

  it('detects dirty state', () => {
    const baseline = form();
    const dirty = { ...baseline, allow_anonymous_mcp: false };
    expect(hasMcpPolicyChanges(dirty, baseline)).toBe(true);
    expect(hasMcpPolicyChanges(baseline, baseline)).toBe(false);
  });

  it('clears default_enabled when in_ceiling is turned off', () => {
    const baseline = form({
      tools: [
        {
          tool_id: 'ping',
          description: 'Health check',
          toolset: 'health',
          in_ceiling: true,
          default_enabled: true,
          anonymous_enabled: true,
        },
      ],
    });
    const next = patchToolFlag(baseline, 'ping', 'in_ceiling', false);
    expect(next.tools[0]).toMatchObject({ in_ceiling: false, default_enabled: false });
  });
});
