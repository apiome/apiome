/**
 * Per-key MCP capability form helpers — MTG-4.3 (#4782).
 */

import {
  buildMcpKeyCapabilitiesPutBody,
  groupKeyToolsByToolset,
  hasMcpKeyCapabilityChanges,
  mcpKeyCapabilityFormFromSources,
  patchKeyToolEnabled,
  patchKeyToolsetEnabled,
  setKeyCapabilityMode,
  validateMcpKeyCapabilityForm,
  type McpKeyCapabilityFormState,
} from '../src/app/ade/dashboard/tenants/mcpKeyCapabilityForm';
import type { McpToolCatalogItem } from '../src/app/ade/dashboard/tenants/mcpPolicyApi';

const CATALOG: McpToolCatalogItem[] = [
  { id: 'ping', description: 'Health check', toolset: 'health' },
  { id: 'spec.list', description: 'List specs', toolset: 'catalog' },
  { id: 'spec.search', description: 'Search specs', toolset: 'search' },
];

const CEILING = ['ping', 'spec.list'];

function form(
  overrides: Partial<McpKeyCapabilityFormState> = {},
): McpKeyCapabilityFormState {
  return {
    ...mcpKeyCapabilityFormFromSources('explicit', ['ping'], CATALOG, CEILING),
    ...overrides,
  };
}

describe('mcpKeyCapabilityFormFromSources', () => {
  it('locks tools outside the ceiling and clears their enable flag', () => {
    const f = mcpKeyCapabilityFormFromSources(
      'explicit',
      ['ping', 'spec.search'],
      CATALOG,
      CEILING,
    );
    expect(f.tools.find((t) => t.tool_id === 'ping')).toMatchObject({
      in_ceiling: true,
      enabled: true,
    });
    expect(f.tools.find((t) => t.tool_id === 'spec.search')).toMatchObject({
      in_ceiling: false,
      enabled: false,
    });
  });

  it('clears enable flags visually under inherit even when stored list has tools', () => {
    const f = mcpKeyCapabilityFormFromSources(
      'inherit',
      ['ping', 'spec.list'],
      CATALOG,
      CEILING,
    );
    expect(f.mode).toBe('inherit');
    expect(f.tools.every((t) => !t.enabled)).toBe(true);
  });
});

describe('buildMcpKeyCapabilitiesPutBody', () => {
  it('omits enabled_tools for inherit', () => {
    expect(buildMcpKeyCapabilitiesPutBody(form({ mode: 'inherit' }))).toEqual({
      mode: 'inherit',
    });
  });

  it('sends only ceiling-enabled tools for explicit', () => {
    const f = mcpKeyCapabilityFormFromSources(
      'explicit',
      ['ping', 'spec.search'],
      CATALOG,
      CEILING,
    );
    expect(buildMcpKeyCapabilitiesPutBody(f)).toEqual({
      mode: 'explicit',
      enabled_tools: ['ping'],
    });
  });
});

describe('validateMcpKeyCapabilityForm', () => {
  it('rejects enabled tools outside the ceiling', () => {
    const f = form();
    f.tools = f.tools.map((row) =>
      row.tool_id === 'spec.search' ? { ...row, enabled: true } : row,
    );
    expect(validateMcpKeyCapabilityForm(f)).toMatch(/exceeds tenant ceiling/);
  });

  it('accepts inherit and ceiling-safe explicit', () => {
    expect(validateMcpKeyCapabilityForm(form({ mode: 'inherit' }))).toBeNull();
    expect(validateMcpKeyCapabilityForm(form())).toBeNull();
  });
});

describe('hasMcpKeyCapabilityChanges', () => {
  it('ignores tool enable diffs when both are inherit', () => {
    const a = form({ mode: 'inherit' });
    const b = mcpKeyCapabilityFormFromSources('inherit', ['ping'], CATALOG, CEILING);
    expect(hasMcpKeyCapabilityChanges(a, b)).toBe(false);
  });

  it('detects mode and enable-set changes', () => {
    const baseline = form();
    expect(
      hasMcpKeyCapabilityChanges(setKeyCapabilityMode(baseline, 'inherit'), baseline),
    ).toBe(true);
    expect(
      hasMcpKeyCapabilityChanges(patchKeyToolsetEnabled(baseline, 'catalog', true), baseline),
    ).toBe(true);
  });
});

describe('patch + group', () => {
  it('patchKeyToolsetEnabled only flips unlocked tools', () => {
    const next = patchKeyToolsetEnabled(form({ mode: 'explicit' }), 'search', true);
    expect(next.tools.find((t) => t.tool_id === 'spec.search')?.enabled).toBe(false);
  });

  it('patchKeyToolEnabled is a no-op outside the ceiling', () => {
    const next = patchKeyToolEnabled(form(), 'spec.search', true);
    expect(next.tools.find((t) => t.tool_id === 'spec.search')?.enabled).toBe(false);
  });

  it('groupKeyToolsByToolset follows MCP_TOOLSET_ORDER', () => {
    const groups = groupKeyToolsByToolset(form().tools);
    expect(groups.map((g) => g.toolset)).toEqual(['health', 'catalog', 'search']);
    expect(groups[0].enableState).toBe('all');
    expect(groups[2].unlockedCount).toBe(0);
  });
});
