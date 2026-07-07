/**
 * Unit tests for the pure MCP capability presence-matrix helpers (V2-MCP-30.2 / MCAT-16.2).
 *
 * Exercises the presence reconstruction and lifespan classification the {@link CapabilityPresenceMatrixPanel}
 * renders — kept free of React so the projection is verified directly. The acceptance criteria checked
 * here: presence reconstructs correctly for a multi-version endpoint; a rename reads as its old name
 * removed and its new name added (handled per the diff record); added-vs-modified is adjacency-based and
 * key-order-independent; and the lifespan categories (stable / new / volatile / removed) and headline
 * metrics are computed from the presence pattern.
 */
import type { McpCapabilityItem, McpVersionDetail } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';
import {
  mcpCapabilityKey,
  mcpCapabilitySignature,
  mcpMatrixCellLabel,
  mcpMatrixCellStateLabel,
  mcpMatrixColumnDateLabel,
  mcpMatrixColumnLabel,
  mcpMatrixKindLabel,
  mcpMatrixLifespanLabel,
  mcpPresenceMatrix,
  type McpMatrixRow,
} from '../src/app/components/ade/dashboard/mcp/mcpPresenceMatrixUi';

/** Build a capability item with sensible defaults. */
function item(overrides: Partial<McpCapabilityItem> = {}): McpCapabilityItem {
  return {
    item_type: overrides.item_type ?? 'tool',
    name: overrides.name ?? 'search',
    title: overrides.title ?? null,
    description: overrides.description ?? null,
    uri: overrides.uri ?? null,
    uri_template: overrides.uri_template ?? null,
    input_schema: overrides.input_schema ?? null,
    output_schema: overrides.output_schema ?? null,
    annotations: overrides.annotations ?? null,
    ordinal: overrides.ordinal ?? 0,
  };
}

/** Build a version-detail snapshot with the given items. */
function version(overrides: Partial<McpVersionDetail> = {}): McpVersionDetail {
  return {
    id: overrides.id ?? 'ver-1',
    version_seq: overrides.version_seq ?? 1,
    version_tag: overrides.version_tag ?? null,
    server_name: overrides.server_name ?? null,
    server_version: overrides.server_version ?? null,
    server_title: overrides.server_title ?? null,
    protocol_version: overrides.protocol_version ?? null,
    instructions: overrides.instructions ?? null,
    score: overrides.score ?? null,
    grade: overrides.grade ?? null,
    is_current: overrides.is_current ?? false,
    discovered_at: overrides.discovered_at ?? null,
    items: overrides.items ?? [],
  };
}

/** Find a row by capability name (the tests use unique names per kind). */
function rowByName(rows: readonly McpMatrixRow[], name: string): McpMatrixRow {
  const row = rows.find((r) => r.name === name);
  if (!row) throw new Error(`row ${name} not found`);
  return row;
}

describe('mcpCapabilitySignature', () => {
  it('is stable across object key order (canonical serialization)', () => {
    const a = item({ input_schema: { a: 1, b: { c: 2, d: 3 } } });
    const b = item({ input_schema: { b: { d: 3, c: 2 }, a: 1 } });
    expect(mcpCapabilitySignature(a)).toBe(mcpCapabilitySignature(b));
  });

  it('changes when a fingerprint-relevant field changes', () => {
    const a = item({ description: 'first' });
    const b = item({ description: 'second' });
    expect(mcpCapabilitySignature(a)).not.toBe(mcpCapabilitySignature(b));
  });

  it('ignores fields outside a kind’s fingerprint projection (a tool’s uri)', () => {
    // `uri` is not part of a tool's projection, so setting it must not read as a modification.
    const a = item({ item_type: 'tool', uri: null });
    const b = item({ item_type: 'tool', uri: 'ignored://x' });
    expect(mcpCapabilitySignature(a)).toBe(mcpCapabilitySignature(b));
  });
});

describe('mcpPresenceMatrix — presence reconstruction', () => {
  it('reconstructs presence correctly across a multi-version endpoint', () => {
    const versions = [
      version({ id: 'v1', version_seq: 1, items: [item({ name: 'alpha' }), item({ name: 'beta' })] }),
      // beta removed, gamma added.
      version({ id: 'v2', version_seq: 2, items: [item({ name: 'alpha' }), item({ name: 'gamma' })] }),
      version({
        id: 'v3',
        version_seq: 3,
        is_current: true,
        items: [item({ name: 'alpha' }), item({ name: 'gamma' })],
      }),
    ];
    const matrix = mcpPresenceMatrix(versions);

    expect(matrix.columns.map((c) => c.version_id)).toEqual(['v1', 'v2', 'v3']);
    expect(matrix.currentIndex).toBe(2);
    expect(matrix.totalCapabilities).toBe(3);

    expect(rowByName(matrix.rows, 'alpha').cells).toEqual(['added', 'present', 'present']);
    expect(rowByName(matrix.rows, 'beta').cells).toEqual(['added', 'absent', 'absent']);
    expect(rowByName(matrix.rows, 'gamma').cells).toEqual(['absent', 'added', 'present']);
  });

  it('sorts columns oldest-first regardless of input order', () => {
    const matrix = mcpPresenceMatrix([
      version({ id: 'v3', version_seq: 3, items: [item({ name: 'alpha' })] }),
      version({ id: 'v1', version_seq: 1, items: [item({ name: 'alpha' })] }),
      version({ id: 'v2', version_seq: 2, items: [item({ name: 'alpha' })] }),
    ]);
    expect(matrix.columns.map((c) => c.version_seq)).toEqual([1, 2, 3]);
    expect(rowByName(matrix.rows, 'alpha').cells).toEqual(['added', 'present', 'present']);
  });

  it('marks a changed capability modified and an unchanged one present (adjacency-based)', () => {
    const matrix = mcpPresenceMatrix([
      version({ id: 'v1', version_seq: 1, items: [item({ name: 'alpha', input_schema: { x: 1 } })] }),
      // Same schema — carried, unchanged.
      version({ id: 'v2', version_seq: 2, items: [item({ name: 'alpha', input_schema: { x: 1 } })] }),
      // Schema changed — modified.
      version({
        id: 'v3',
        version_seq: 3,
        is_current: true,
        items: [item({ name: 'alpha', input_schema: { x: 2 } })],
      }),
    ]);
    expect(rowByName(matrix.rows, 'alpha').cells).toEqual(['added', 'present', 'modified']);
    expect(rowByName(matrix.rows, 'alpha').modifiedCount).toBe(1);
  });

  it('does not read a key-order-only schema difference as modified', () => {
    const matrix = mcpPresenceMatrix([
      version({ id: 'v1', version_seq: 1, items: [item({ name: 'alpha', input_schema: { a: 1, b: 2 } })] }),
      version({ id: 'v2', version_seq: 2, items: [item({ name: 'alpha', input_schema: { b: 2, a: 1 } })] }),
    ]);
    expect(rowByName(matrix.rows, 'alpha').cells).toEqual(['added', 'present']);
  });

  it('treats a rename as the old name removed and the new name added (per the diff record)', () => {
    const matrix = mcpPresenceMatrix([
      version({ id: 'v1', version_seq: 1, items: [item({ name: 'search' })] }),
      version({ id: 'v2', version_seq: 2, is_current: true, items: [item({ name: 'find' })] }),
    ]);
    expect(matrix.totalCapabilities).toBe(2);
    expect(rowByName(matrix.rows, 'search').cells).toEqual(['added', 'absent']);
    expect(rowByName(matrix.rows, 'find').cells).toEqual(['absent', 'added']);
  });

  it('re-adds (not carries) a capability that reappears after a gap', () => {
    const matrix = mcpPresenceMatrix([
      version({ id: 'v1', version_seq: 1, items: [item({ name: 'alpha' })] }),
      version({ id: 'v2', version_seq: 2, items: [] }),
      version({ id: 'v3', version_seq: 3, is_current: true, items: [item({ name: 'alpha' })] }),
    ]);
    expect(rowByName(matrix.rows, 'alpha').cells).toEqual(['added', 'absent', 'added']);
    expect(rowByName(matrix.rows, 'alpha').hasGap).toBe(true);
  });

  it('distinguishes capabilities of the same name but different kinds', () => {
    const matrix = mcpPresenceMatrix([
      version({
        id: 'v1',
        version_seq: 1,
        is_current: true,
        items: [item({ item_type: 'tool', name: 'data' }), item({ item_type: 'resource', name: 'data', uri: 'x://d' })],
      }),
    ]);
    expect(matrix.totalCapabilities).toBe(2);
    expect(matrix.rows.map((r) => r.key)).toContain(mcpCapabilityKey('tool', 'data'));
    expect(matrix.rows.map((r) => r.key)).toContain(mcpCapabilityKey('resource', 'data'));
  });

  it('skips unnamed items (no stable identity to track)', () => {
    const matrix = mcpPresenceMatrix([
      version({ id: 'v1', version_seq: 1, is_current: true, items: [item({ name: '' }), item({ name: 'alpha' })] }),
    ]);
    expect(matrix.totalCapabilities).toBe(1);
    expect(matrix.rows[0].name).toBe('alpha');
  });

  it('returns an empty matrix for no versions', () => {
    const matrix = mcpPresenceMatrix([]);
    expect(matrix.columns).toEqual([]);
    expect(matrix.rows).toEqual([]);
    expect(matrix.currentIndex).toBe(-1);
    expect(matrix.totalCapabilities).toBe(0);
  });
});

describe('mcpPresenceMatrix — lifespan classification & metrics', () => {
  const matrix = mcpPresenceMatrix([
    version({
      id: 'v1',
      version_seq: 1,
      items: [item({ name: 'stableTool' }), item({ name: 'goneTool' }), item({ name: 'flakyTool' })],
    }),
    version({
      id: 'v2',
      version_seq: 2,
      // goneTool removed; flakyTool gaps out.
      items: [item({ name: 'stableTool' })],
    }),
    version({
      id: 'v3',
      version_seq: 3,
      is_current: true,
      // flakyTool reappears; newTool appears for the first time.
      items: [item({ name: 'stableTool' }), item({ name: 'flakyTool' }), item({ name: 'newTool' })],
    }),
  ]);

  it('classifies a capability present since v1 through current as stable', () => {
    expect(rowByName(matrix.rows, 'stableTool').lifespan).toBe('stable');
    expect(rowByName(matrix.rows, 'stableTool').currentlyPresent).toBe(true);
  });

  it('classifies a capability first seen only in the current column as new', () => {
    expect(rowByName(matrix.rows, 'newTool').lifespan).toBe('new');
  });

  it('classifies a reappearing capability as volatile', () => {
    expect(rowByName(matrix.rows, 'flakyTool').lifespan).toBe('volatile');
    expect(rowByName(matrix.rows, 'flakyTool').hasGap).toBe(true);
  });

  it('classifies a capability absent from the current column as removed', () => {
    expect(rowByName(matrix.rows, 'goneTool').lifespan).toBe('removed');
    expect(rowByName(matrix.rows, 'goneTool').currentlyPresent).toBe(false);
  });

  it('rolls up the headline metrics', () => {
    expect(matrix.totalCapabilities).toBe(4);
    expect(matrix.currentCount).toBe(3); // stable, flaky, new
    expect(matrix.removedCount).toBe(1); // gone
    expect(matrix.volatileCount).toBe(1); // flaky
    expect(matrix.newCount).toBe(1); // new
  });

  it('falls back to the newest column as current when none is flagged', () => {
    const noCurrent = mcpPresenceMatrix([
      version({ id: 'v1', version_seq: 1, items: [item({ name: 'alpha' })] }),
      version({ id: 'v2', version_seq: 2, items: [item({ name: 'alpha' })] }),
    ]);
    expect(noCurrent.currentIndex).toBe(1);
    expect(rowByName(noCurrent.rows, 'alpha').currentlyPresent).toBe(true);
  });
});

describe('presence-matrix labels', () => {
  const column = {
    version_id: 'v1',
    version_seq: 4,
    version_tag: null as string | null,
    discovered_at: null as string | null,
    is_current: true,
  };

  it('labels a column by its sequence', () => {
    expect(mcpMatrixColumnLabel(column)).toBe('v4');
  });

  it('prefers a version tag, then discovered_at, then the sequence for the date label', () => {
    expect(mcpMatrixColumnDateLabel({ ...column, version_tag: 'rc-1' })).toBe('rc-1');
    expect(mcpMatrixColumnDateLabel({ ...column, discovered_at: '2026-07-01T10:00:00Z' })).toContain('2026');
    expect(mcpMatrixColumnDateLabel(column)).toBe('v4');
  });

  it('humanizes kinds, cell states, and lifespans', () => {
    expect(mcpMatrixKindLabel('resource_template')).toBe('Resource template');
    expect(mcpMatrixKindLabel('tool')).toBe('Tool');
    expect(mcpMatrixCellStateLabel('modified')).toBe('modified');
    expect(mcpMatrixLifespanLabel('volatile')).toBe('Volatile');
  });

  it('builds an accessible cell label naming the capability, snapshot, and state', () => {
    const matrix = mcpPresenceMatrix([
      version({ id: 'v1', version_seq: 2, is_current: true, items: [item({ name: 'alpha' })] }),
    ]);
    const row = rowByName(matrix.rows, 'alpha');
    expect(mcpMatrixCellLabel(row, matrix.columns[0], row.cells[0])).toBe('alpha in v2: added');
  });
});
