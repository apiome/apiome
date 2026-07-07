/**
 * Unit tests for the pure safety & annotation posture helpers (V2-MCP-29.4 / MCAT-15.4).
 *
 * Covers the per-tool hint matrix (tri-state cells, tool-only rows, unnamed fallback), the auth
 * posture resolution (anonymous / authenticated / unknown), the roll-up (counts, annotated tallies,
 * the fully-unannotated flag, destructive-without-auth cross-reference), and the headline chips.
 */
import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';
import {
  SAFETY_HINT_COLUMNS,
  UNNAMED_TOOL_LABEL,
  mcpSafetyAuth,
  mcpSafetyHeadlineChips,
  mcpSafetyPosture,
  mcpToolSafetyRows,
} from '../src/app/components/ade/dashboard/mcp/mcpSafetyPostureUi';

/** Build a `tool` capability item with the given name and raw annotations object. */
function tool(name: string, annotations: Record<string, unknown> | null): McpCapabilityItem {
  return {
    item_type: 'tool',
    name,
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations,
    ordinal: 0,
  };
}

/** Build a non-tool capability item (resource / prompt), which must never form a matrix row. */
function nonTool(itemType: string, name: string): McpCapabilityItem {
  return { ...tool(name, { readOnlyHint: true }), item_type: itemType };
}

describe('mcpToolSafetyRows', () => {
  it('returns an empty array for null/undefined items', () => {
    expect(mcpToolSafetyRows(null)).toEqual([]);
    expect(mcpToolSafetyRows(undefined)).toEqual([]);
    expect(mcpToolSafetyRows([])).toEqual([]);
  });

  it('includes only tool items, indexed by tool ordinal (non-tools skipped)', () => {
    const rows = mcpToolSafetyRows([
      tool('search', { readOnlyHint: true }),
      nonTool('resource', 'file'),
      tool('write', { destructiveHint: true }),
    ]);
    expect(rows.map((r) => r.name)).toEqual(['search', 'write']);
    expect(rows.map((r) => r.index)).toEqual([0, 1]);
  });

  it('resolves each hint to a tri-state: asserted / denied / unset', () => {
    const [row] = mcpToolSafetyRows([
      tool('mixed', { readOnlyHint: true, destructiveHint: false }),
    ]);
    expect(row.cells.readOnlyHint).toBe('asserted');
    expect(row.cells.destructiveHint).toBe('denied');
    // Hints the server never declared are `unset`.
    expect(row.cells.idempotentHint).toBe('unset');
    expect(row.cells.openWorldHint).toBe('unset');
  });

  it('treats non-boolean and absent annotations as unset', () => {
    const [row] = mcpToolSafetyRows([
      tool('weird', { readOnlyHint: 'yes', destructiveHint: 1, openWorldHint: null }),
    ]);
    expect(row.cells.readOnlyHint).toBe('unset');
    expect(row.cells.destructiveHint).toBe('unset');
    expect(row.cells.openWorldHint).toBe('unset');
    expect(row.unannotated).toBe(true);
  });

  it('flags a tool with no declared hints as unannotated', () => {
    const [none, some] = mcpToolSafetyRows([
      tool('bare', null),
      tool('annotated', { idempotentHint: false }),
    ]);
    expect(none.unannotated).toBe(true);
    // An explicit `false` still counts as annotated — the server made an assertion.
    expect(some.unannotated).toBe(false);
  });

  it('marks the tool destructive only when destructiveHint is asserted true', () => {
    const rows = mcpToolSafetyRows([
      tool('a', { destructiveHint: true }),
      tool('b', { destructiveHint: false }),
      tool('c', { readOnlyHint: true }),
    ]);
    expect(rows.map((r) => r.destructive)).toEqual([true, false, false]);
  });

  it('falls back to a placeholder name for an unnamed tool', () => {
    const [row] = mcpToolSafetyRows([tool('   ', { readOnlyHint: true })]);
    expect(row.displayName).toBe(UNNAMED_TOOL_LABEL);
  });
});

describe('mcpSafetyAuth', () => {
  it('resolves an absent/blank auth type to the unknown posture', () => {
    for (const value of [null, undefined, '', '   ']) {
      const auth = mcpSafetyAuth(value);
      expect(auth.posture).toBe('unknown');
      expect(auth.tone).toBe('slate');
      expect(auth.label).toBe('Auth unknown');
    }
  });

  it('resolves an explicit `none` to the anonymous posture', () => {
    const auth = mcpSafetyAuth('none');
    expect(auth.posture).toBe('anonymous');
    expect(auth.label).toBe('No auth');
  });

  it('resolves a secret-bearing scheme to authenticated, reusing the shared auth badge', () => {
    expect(mcpSafetyAuth('bearer')).toMatchObject({ posture: 'authenticated', label: 'bearer' });
    expect(mcpSafetyAuth('oauth2')).toMatchObject({
      posture: 'authenticated',
      label: 'OAuth 2.1',
      tone: 'violet',
    });
  });

  it('is case-insensitive and trims whitespace', () => {
    expect(mcpSafetyAuth('  NONE ').posture).toBe('anonymous');
    expect(mcpSafetyAuth('Bearer').posture).toBe('authenticated');
  });
});

describe('mcpSafetyPosture', () => {
  const surface: McpCapabilityItem[] = [
    tool('search', { readOnlyHint: true }),
    tool('read_file', { readOnlyHint: true }),
    tool('delete_record', { destructiveHint: true, openWorldHint: true }),
    tool('sync', { idempotentHint: true }),
    tool('mystery', null),
  ];

  it('counts each hint over the tools that assert it', () => {
    const posture = mcpSafetyPosture(surface, 'bearer');
    expect(posture.counts).toEqual({
      readOnlyHint: 2,
      destructiveHint: 1,
      idempotentHint: 1,
      openWorldHint: 1,
    });
  });

  it('tallies total / annotated / unannotated tools', () => {
    const posture = mcpSafetyPosture(surface, 'bearer');
    expect(posture.totalTools).toBe(5);
    expect(posture.annotatedTools).toBe(4);
    expect(posture.unannotatedTools).toBe(1);
    expect(posture.fullyUnannotated).toBe(false);
  });

  it('sets fullyUnannotated only when tools exist but none declares a hint', () => {
    expect(mcpSafetyPosture([tool('a', null), tool('b', {})], 'none').fullyUnannotated).toBe(true);
    // An empty surface is not "unannotated" — there is nothing to annotate.
    expect(mcpSafetyPosture([], 'none').fullyUnannotated).toBe(false);
    expect(mcpSafetyPosture([], 'none').totalTools).toBe(0);
  });

  it('surfaces destructive-without-auth only on an anonymous endpoint', () => {
    const anon = mcpSafetyPosture(surface, 'none');
    expect(anon.destructiveWithoutAuth.map((r) => r.name)).toEqual(['delete_record']);

    // An authenticated endpoint gates the same destructive tool, so it is not flagged.
    expect(mcpSafetyPosture(surface, 'bearer').destructiveWithoutAuth).toEqual([]);
    // An unknown auth type is treated conservatively — never a false no-auth alarm.
    expect(mcpSafetyPosture(surface, null).destructiveWithoutAuth).toEqual([]);
  });
});

describe('mcpSafetyHeadlineChips', () => {
  it('lists only asserted hints, risk-first, with counts', () => {
    const posture = mcpSafetyPosture(
      [
        tool('a', { readOnlyHint: true }),
        tool('b', { readOnlyHint: true }),
        tool('c', { destructiveHint: true }),
        tool('d', { openWorldHint: true }),
      ],
      'bearer',
    );
    const chips = mcpSafetyHeadlineChips(posture);
    // Order: destructive → open-world → read-only (idempotent has zero, so omitted).
    expect(chips.map((c) => `${c.count} ${c.label}`)).toEqual([
      '1 Destructive',
      '1 Open-world',
      '2 Read-only',
    ]);
    expect(chips.find((c) => c.key === 'destructiveHint')?.risk).toBe(true);
    expect(chips.find((c) => c.key === 'readOnlyHint')?.risk).toBe(false);
  });

  it('returns no chips when no hint is asserted', () => {
    const posture = mcpSafetyPosture([tool('a', null), tool('b', { readOnlyHint: false })], 'none');
    expect(mcpSafetyHeadlineChips(posture)).toEqual([]);
  });
});

describe('SAFETY_HINT_COLUMNS', () => {
  it('covers the four hints in read-only/destructive/idempotent/open-world order', () => {
    expect(SAFETY_HINT_COLUMNS.map((c) => c.key)).toEqual([
      'readOnlyHint',
      'destructiveHint',
      'idempotentHint',
      'openWorldHint',
    ]);
    // Destructive and open-world are the risk signals.
    expect(SAFETY_HINT_COLUMNS.filter((c) => c.risk).map((c) => c.key)).toEqual([
      'destructiveHint',
      'openWorldHint',
    ]);
  });
});
