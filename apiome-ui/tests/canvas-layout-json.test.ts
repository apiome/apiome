import { describe, expect, test } from '@jest/globals';
import type { Edge } from '@xyflow/react';
import {
  buildCanvasLayoutJsonDocument,
  CANVAS_LAYOUT_JSON_FORMAT_VERSION,
  filterCanvasLayoutForTargetClasses,
  mergeSavedEdgeHandles,
  parseCanvasLayoutJson,
} from '../src/app/utils/canvas-layout-json';

describe('canvas-layout-json', () => {
  test('buildCanvasLayoutJsonDocument includes format version and required fields', () => {
    const doc = buildCanvasLayoutJsonDocument({
      layoutName: 'Dev',
      viewport: { x: 1, y: 2, zoom: 0.5 },
      nodes: [{ id: 'a', type: 'classNode' }],
      edges: [{ id: 'e1', source: 'a', target: 'b' }],
      groups: [{ id: 'g1', name: 'G', nodeIds: ['a'], position: { x: 0, y: 0 }, dimensions: { width: 100, height: 100 } }],
      gridSettings: { size: 20, snapToGrid: true, showGrid: true, gridStyle: 'dots' },
      generator: { name: 'apiome-ui' },
    });
    expect(doc.formatVersion).toBe(CANVAS_LAYOUT_JSON_FORMAT_VERSION);
    expect(doc.layoutName).toBe('Dev');
    expect(doc.exportedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(doc.nodes).toHaveLength(1);
    expect(doc.edges).toHaveLength(1);
    expect(doc.groups).toHaveLength(1);
    expect(doc.generator?.name).toBe('apiome-ui');
  });

  test('parseCanvasLayoutJson accepts valid v1 document', () => {
    const raw = {
      formatVersion: 1,
      exportedAt: '2026-03-29T12:00:00.000Z',
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [],
      edges: [],
    };
    const r = parseCanvasLayoutJson(raw);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.doc.formatVersion).toBe(1);
      expect(r.doc.exportedAt).toBe('2026-03-29T12:00:00.000Z');
      expect(r.doc.viewport).toEqual({ x: 0, y: 0, zoom: 1 });
    }
  });

  test('parseCanvasLayoutJson coerces non-finite viewport values to defaults', () => {
    const raw = {
      formatVersion: 1,
      exportedAt: '2026-03-29T12:00:00.000Z',
      viewport: { x: 'bad', y: NaN, zoom: Infinity },
      nodes: [],
      edges: [],
    };
    const r = parseCanvasLayoutJson(raw);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.doc.viewport).toEqual({ x: 0, y: 0, zoom: 1 });
    }
  });

  test('parseCanvasLayoutJson coerces missing viewport fields to defaults', () => {
    const raw = {
      formatVersion: 1,
      exportedAt: '2026-03-29T12:00:00.000Z',
      viewport: {},
      nodes: [],
      edges: [],
    };
    const r = parseCanvasLayoutJson(raw);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.doc.viewport).toEqual({ x: 0, y: 0, zoom: 1 });
    }
  });

  test('parseCanvasLayoutJson rejects wrong format version', () => {
    const r = parseCanvasLayoutJson({
      formatVersion: 99,
      exportedAt: '2026-03-29T12:00:00.000Z',
      viewport: {},
      nodes: [],
      edges: [],
    });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error).toContain('formatVersion');
    }
  });

  test('filterCanvasLayoutForTargetClasses drops unknown class ids and group nodes', () => {
    const doc = buildCanvasLayoutJsonDocument({
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [
        { id: 'keep', type: 'classNode', position: { x: 10, y: 20 } },
        { id: 'drop', type: 'classNode', position: { x: 1, y: 2 } },
        { id: 'g-old', type: 'groupNode', position: { x: 0, y: 0 } },
      ],
      edges: [
        { id: 'e1', source: 'keep', target: 'drop' },
        { id: 'e2', source: 'keep', target: 'keep' },
      ],
      groups: [{ id: 'g1', name: 'G', nodeIds: ['keep', 'drop'], position: { x: 0, y: 0 }, dimensions: { width: 1, height: 1 } }],
    });
    const valid = new Set(['keep']);
    const filtered = filterCanvasLayoutForTargetClasses(doc, valid);
    expect(filtered.nodes).toHaveLength(1);
    expect(filtered.nodes[0].id).toBe('keep');
    expect(filtered.nodes[0].position).toEqual({ x: 10, y: 20 });
    expect(filtered.droppedClassCount).toBe(1);
    expect(filtered.nodePositions.keep).toEqual({ x: 10, y: 20 });
    expect(filtered.edges).toHaveLength(1);
    expect((filtered.edges[0] as { source: string; target: string }).source).toBe('keep');
    expect((filtered.edges[0] as { source: string; target: string }).target).toBe('keep');
    expect((filtered.groups[0] as { nodeIds: string[] }).nodeIds).toEqual(['keep']);
  });

  test('filterCanvasLayoutForTargetClasses accepts quick snapshot style nodes from mapNodesForLayoutSave', () => {
    const doc = buildCanvasLayoutJsonDocument({
      viewport: { x: 2, y: -3, zoom: 0.75 },
      nodes: [
        {
          id: 'c1',
          type: 'classNode',
          position: { x: 11, y: 22 },
          dimensions: { width: 180, height: 90 },
        },
      ],
      edges: [{ id: 'e1', source: 'c1', target: 'c1', sourceHandle: 'h1', targetHandle: 'h2' }],
      groups: [{ id: 'g1', name: 'G', nodeIds: ['c1'], position: { x: 0, y: 0 }, dimensions: { width: 50, height: 50 } }],
    });
    const filtered = filterCanvasLayoutForTargetClasses(doc, new Set(['c1']));
    expect(filtered.viewport).toEqual({ x: 2, y: -3, zoom: 0.75 });
    expect(filtered.nodes).toHaveLength(1);
    expect(filtered.nodes[0]).toEqual({ id: 'c1', position: { x: 11, y: 22 } });
    expect(filtered.edges).toHaveLength(1);
    expect((filtered.groups[0] as { id: string }).id).toBe('g1');
  });

  test('filterCanvasLayoutForTargetClasses drops nodes with invalid positions', () => {
    const doc = buildCanvasLayoutJsonDocument({
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [
        { id: 'valid', type: 'classNode', position: { x: 5, y: 10 } },
        { id: 'bad-pos', type: 'classNode', position: { x: 'oops', y: 0 } },
        { id: 'no-pos', type: 'classNode' },
      ],
      edges: [],
    });
    const valid = new Set(['valid', 'bad-pos', 'no-pos']);
    const filtered = filterCanvasLayoutForTargetClasses(doc, valid);
    // Only 'valid' has a valid numeric position
    expect(filtered.nodes).toHaveLength(1);
    expect(filtered.nodes[0].id).toBe('valid');
    expect(filtered.nodePositions).toEqual({ valid: { x: 5, y: 10 } });
  });

  test('mergeSavedEdgeHandles overlays handles by edge id', () => {
    const current: Edge[] = [
      {
        id: 'e1',
        source: 'a',
        target: 'b',
        sourceHandle: 'old-src',
        targetHandle: 'old-tgt',
      } as Edge,
    ];
    const merged = mergeSavedEdgeHandles(current, [
      { id: 'e1', sourceHandle: 'new-src', targetHandle: 'new-tgt' },
    ]);
    expect(merged[0].sourceHandle).toBe('new-src');
    expect(merged[0].targetHandle).toBe('new-tgt');
  });

  test('mergeSavedEdgeHandles ignores entries without string handles', () => {
    const current: Edge[] = [{ id: 'e1', source: 'a', target: 'b' } as Edge];
    expect(mergeSavedEdgeHandles(current, [{ id: 'e1', sourceHandle: 1 }])).toEqual(current);
  });

  test('mergeSavedEdgeHandles returns current when saved is empty', () => {
    const current: Edge[] = [{ id: 'e1', source: 'a', target: 'b' } as Edge];
    expect(mergeSavedEdgeHandles(current, [])).toEqual(current);
    expect(mergeSavedEdgeHandles(current, undefined)).toEqual(current);
  });
});
