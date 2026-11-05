/**
 * exportViz — the visualization modes model (MFX-45.4, #4377).
 *
 * Pinned on real manifests captured from apiome-rest (`fixtures/exportVizGraphs.json`):
 *
 *  1. Each mode is offered for its family and absent otherwise: the descriptor declares it and the
 *     manifest has something to draw.
 *  2. The chosen view persists per target for the session — and never breaks when storage is blocked.
 *  3. Every graph lays out in columns, a node one column right of the furthest node pointing at it.
 *  4. Selection, summary and labels.
 */

import * as fs from 'fs';
import * as path from 'path';
import {
  availableVizModes,
  loadVizChoice,
  nodeKindLabel,
  saveVizChoice,
  vizChoiceKey,
  vizColumns,
  vizEdgeLabel,
  vizGraphLayout,
  vizNodeAriaLabel,
  vizSelection,
  vizSummary,
  VIZ_GEOMETRY,
  type ExportVizMode,
  type VizGraph,
} from '../src/app/components/ade/dashboard/export/exportViz';
import type { RelationalSchema } from '../src/app/components/ade/dashboard/export/exportErd';

interface Captured {
  viz_modes: ExportVizMode[];
  views: Record<string, VizGraph>;
}
const CAPTURED = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'exportVizGraphs.json'), 'utf-8')) as Record<
  'proto3' | 'asyncapi' | 'xregistry',
  Captured
>;
const PROTO = CAPTURED.proto3;
const ASYNC = CAPTURED.asyncapi;
const XREG = CAPTURED.xregistry;
const RELATIONAL: RelationalSchema = {
  dialect: 'postgres',
  output: 'ddl',
  schema_name: null,
  tables: [{ name: 't', kind: 'table', entity_key: 'T', synthesized: false, columns: [], primary_key: [], unique: [], foreign_keys: [] }],
};

// ---------------------------------------------------------------------------
// 1. Availability
// ---------------------------------------------------------------------------

describe('availableVizModes', () => {
  it('offers every declared mode that has something to draw, in declared order', () => {
    expect(availableVizModes(PROTO.viz_modes, { views: PROTO.views }).map((m) => m.label)).toEqual([
      'Import graph',
      'Service map',
    ]);
    expect(availableVizModes(ASYNC.viz_modes, { views: ASYNC.views }).map((m) => m.kind)).toEqual(['channel-topology']);
    expect(availableVizModes([{ kind: 'erd', label: 'ERD' }], { relational: RELATIONAL }).map((m) => m.kind)).toEqual(['erd']);
  });

  it('offers nothing a target does not declare, even when the data is there', () => {
    expect(availableVizModes([], { views: PROTO.views, relational: RELATIONAL })).toEqual([]);
  });

  it('leaves out a declared mode with nothing to draw (the manifest is still loading)', () => {
    expect(availableVizModes(PROTO.viz_modes, {})).toEqual([]);
    expect(availableVizModes(PROTO.viz_modes, { views: { 'service-map': PROTO.views['service-map'] } }).map((m) => m.kind)).toEqual([
      'service-map',
    ]);
    expect(availableVizModes([{ kind: 'erd', label: 'ERD' }], { relational: { ...RELATIONAL, tables: [] } })).toEqual([]);
  });

  it('falls back to the data when the declaration is unknown (an older server)', () => {
    expect(availableVizModes(undefined, { relational: RELATIONAL, views: PROTO.views }).map((m) => m.label)).toEqual([
      'ERD',
      'Import graph',
      'Service map',
    ]);
    expect(availableVizModes(undefined, { views: { bogus: PROTO.views['service-map'] } })).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 2. The chosen view, per target, for the session
// ---------------------------------------------------------------------------

describe('loadVizChoice / saveVizChoice', () => {
  beforeEach(() => window.sessionStorage.clear());
  afterEach(() => jest.restoreAllMocks());

  it('keeps the view chosen for each target separately', () => {
    saveVizChoice('protobuf', 'service-map');
    saveVizChoice('asyncapi-3', 'channel-topology');
    expect(window.sessionStorage.getItem(vizChoiceKey('protobuf'))).toBe('service-map');
    expect(loadVizChoice('protobuf', PROTO.viz_modes)).toBe('service-map');
    expect(loadVizChoice('asyncapi-3', ASYNC.viz_modes)).toBe('channel-topology');
    expect(loadVizChoice('graphql', [])).toBe('text');
  });

  it('starts on the text when the remembered mode is not offered now, or there is no target', () => {
    saveVizChoice('protobuf', 'service-map');
    expect(loadVizChoice('protobuf', [])).toBe('text');
    expect(loadVizChoice(null, PROTO.viz_modes)).toBe('text');
    saveVizChoice(null, 'erd');
    expect(window.sessionStorage.length).toBe(1);
  });

  it('never throws when storage is blocked', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => saveVizChoice('protobuf', 'service-map')).not.toThrow();
    expect(loadVizChoice('protobuf', PROTO.viz_modes)).toBe('text');
  });
});

// ---------------------------------------------------------------------------
// 3. Layout
// ---------------------------------------------------------------------------

const columnsByKind = (graph: VizGraph) => {
  const columns = vizColumns(graph);
  const out: Record<string, number[]> = {};
  for (const node of graph.nodes) out[node.kind] = [...new Set([...(out[node.kind] ?? []), columns.get(node.id)!])];
  return out;
};

describe('vizColumns / vizGraphLayout', () => {
  it('lays a service map out as services → methods → messages', () => {
    expect(columnsByKind(PROTO.views['service-map'])).toEqual({ service: [0], method: [1], message: [2] });
  });

  it('lays an AsyncAPI topology out as operations → channels → messages', () => {
    expect(columnsByKind(ASYNC.views['channel-topology'])).toEqual({ channel: [1], message: [2], operation: [0] });
  });

  it('lays an xRegistry topology out as groups → messages → event types', () => {
    expect(columnsByKind(XREG.views['channel-topology'])).toEqual({ 'message-group': [0], message: [1], 'event-type': [2] });
  });

  it('puts an importing file left of what it imports', () => {
    const columns = vizColumns(PROTO.views['proto-imports']);
    expect(columns.get('file:api.proto')).toBe(0);
    expect(columns.get('file:google/protobuf/empty.proto')).toBe(1);
  });

  it('survives cycles and self-edges', () => {
    const graph: VizGraph = {
      mode: 'proto-imports',
      nodes: [
        { id: 'a', label: 'a', kind: 'file' },
        { id: 'b', label: 'b', kind: 'file' },
      ],
      edges: [
        { id: '1', source: 'a', target: 'b', kind: 'import' },
        { id: '2', source: 'b', target: 'a', kind: 'import' },
        { id: '3', source: 'a', target: 'a', kind: 'import' },
      ],
    };
    const columns = vizColumns(graph);
    expect(columns.size).toBe(2);
    expect([...columns.values()].every((c) => c <= 2)).toBe(true);
  });

  it('stacks each column in graph order without overlap', () => {
    const placed = vizGraphLayout(PROTO.views['service-map']);
    const methods = placed.filter((p) => p.node.kind === 'method');
    expect(methods.map((p) => p.y)).toEqual(methods.map((_, i) => i * (VIZ_GEOMETRY.nodeHeight + VIZ_GEOMETRY.rowGap)));
    expect(new Set(methods.map((p) => p.x))).toEqual(new Set([VIZ_GEOMETRY.nodeWidth + VIZ_GEOMETRY.columnGap]));
  });
});

// ---------------------------------------------------------------------------
// 4. Selection, summary, labels
// ---------------------------------------------------------------------------

describe('selection, summary and labels', () => {
  it('selects the nodes that stand for a construct', () => {
    expect([...vizSelection(PROTO.views['service-map'], 'Pet')]).toEqual(['message:Pet']);
    expect([...vizSelection(PROTO.views['service-map'], 'GET /pets/{petId}')]).toEqual(['method:default.getPetById']);
    expect(vizSelection(PROTO.views['service-map'], null).size).toBe(0);
  });

  it('summarizes a graph by node kind, external ones counted', () => {
    expect(vizSummary(PROTO.views['proto-imports'])).toBe('2 files · 1 external');
    expect(vizSummary(XREG.views['channel-topology'])).toBe('1 message group · 2 messages · 2 event types');
    expect(nodeKindLabel('unknown')).toBe('unknown');
  });

  it('names a node in words', () => {
    expect(vizNodeAriaLabel({ id: 'm', label: 'WatchOrders', kind: 'method', detail: 'server stream' })).toBe(
      'Method WatchOrders, server stream',
    );
    expect(vizNodeAriaLabel({ id: 'e', label: 'google.protobuf.Empty', kind: 'message', external: true })).toBe(
      'Message google.protobuf.Empty, not in this export',
    );
    expect(vizNodeAriaLabel({ id: 'g', label: 'default', kind: 'message-group' })).toBe('Message group default');
  });

  it('labels the edges worth naming', () => {
    expect(vizEdgeLabel({ id: '1', source: 'a', target: 'b', kind: 'request' })).toBe('request');
    expect(vizEdgeLabel({ id: '1', source: 'a', target: 'b', kind: 'response', label: 'stream' })).toBe('response · stream');
    expect(vizEdgeLabel({ id: '1', source: 'a', target: 'b', kind: 'receives' })).toBe('receives');
    expect(vizEdgeLabel({ id: '1', source: 'a', target: 'b', kind: 'import' })).toBeUndefined();
    expect(vizEdgeLabel({ id: '1', source: 'a', target: 'b', kind: 'carries' })).toBeUndefined();
  });
});
