/**
 * Unit tests for the MCP capability relationship graph presentation helpers (V2-MCP-29.2 /
 * MCAT-15.2, #4632).
 *
 * Exercises the pure client layer over the 15.2 `insight/graph` payload: defensive parsing
 * (including malformed/partial bodies and edges that dangle to a missing node), the legend
 * projection, the edge display-label formatting, and the Mermaid `flowchart` source builder — its
 * node/class emission, directed vs undirected connectors, label sanitization, theme palette
 * selection, and the empty-graph (`null`) case.
 */

import {
  GRAPH_KIND_STYLES,
  mcpGraphEdgeDisplayLabel,
  mcpGraphLegend,
  mcpGraphToMermaid,
  mcpInsightGraphFromPayload,
  type McpCapabilityGraph,
  type McpGraphEdge,
} from '../src/app/components/ade/dashboard/mcp/mcpCapabilityGraphUi';

const ENDPOINT_ID = '11111111-1111-4111-8111-111111111111';
const VERSION_ID = '22222222-2222-4222-8222-222222222222';

/** A representative insight/graph payload as apiome-rest would return it. */
function graphPayload(overrides: Record<string, unknown> = {}) {
  return {
    success: true,
    endpoint_id: ENDPOINT_ID,
    version_id: VERSION_ID,
    version_seq: 2,
    version_tag: '2026-07-06',
    is_current: true,
    graph: {
      nodes: [
        { id: 't_0', item_type: 'tool', name: 'search_docs', title: null, label: 'search_docs', degree: 2 },
        { id: 'r_0', item_type: 'resource', name: 'index', title: null, label: 'index', degree: 1 },
        { id: 'p_0', item_type: 'prompt', name: 'research', title: 'Research', label: 'Research', degree: 1 },
        { id: 'rt_0', item_type: 'resource_template', name: 'byid', title: null, label: 'byid', degree: 0 },
      ],
      edges: [
        { source: 'p_0', target: 't_0', kind: 'prompt_reference', directed: true, label: 'search_docs', signals: ['search_docs'] },
        { source: 't_0', target: 'r_0', kind: 'resource_reference', directed: true, label: 'docs://index', signals: ['docs://index'] },
      ],
      node_count: 4,
      edge_count: 2,
      isolated_count: 1,
      graph_fingerprint: 'abc123',
    },
    ...overrides,
  };
}

describe('mcpInsightGraphFromPayload', () => {
  it('parses a well-formed payload', () => {
    const parsed = mcpInsightGraphFromPayload(graphPayload());
    expect(parsed).not.toBeNull();
    expect(parsed!.version_id).toBe(VERSION_ID);
    expect(parsed!.is_current).toBe(true);
    expect(parsed!.graph.node_count).toBe(4);
    expect(parsed!.graph.edge_count).toBe(2);
    expect(parsed!.graph.isolated_count).toBe(1);
    expect(parsed!.graph.nodes[2].label).toBe('Research');
  });

  it('returns null when there is no resolvable version id', () => {
    expect(mcpInsightGraphFromPayload({ success: false })).toBeNull();
    expect(mcpInsightGraphFromPayload(null)).toBeNull();
  });

  it('drops malformed nodes and derives counts from what survives', () => {
    const parsed = mcpInsightGraphFromPayload(
      graphPayload({
        graph: {
          nodes: [
            { id: 't_0', item_type: 'tool', name: 'a', label: 'a', degree: 0 },
            { item_type: 'tool', name: 'no-id' }, // dropped: no id
          ],
          edges: [],
          node_count: 99, // wire count is ignored; derived from parsed nodes
          isolated_count: 99,
          graph_fingerprint: 'x',
        },
      }),
    );
    expect(parsed!.graph.node_count).toBe(1);
    expect(parsed!.graph.isolated_count).toBe(1);
  });

  it('drops edges that dangle to a missing node', () => {
    const parsed = mcpInsightGraphFromPayload(
      graphPayload({
        graph: {
          nodes: [{ id: 't_0', item_type: 'tool', name: 'a', label: 'a', degree: 0 }],
          edges: [
            { source: 't_0', target: 'ghost', kind: 'shared_type', directed: false, label: 'x', signals: ['x'] },
          ],
          graph_fingerprint: 'x',
        },
      }),
    );
    expect(parsed!.graph.edge_count).toBe(0);
  });

  it('coerces an unknown node type to a safe default and unknown edge kind', () => {
    const parsed = mcpInsightGraphFromPayload(
      graphPayload({
        graph: {
          nodes: [
            { id: 'x_0', item_type: 'weird', name: 'a', label: 'a', degree: 1 },
            { id: 'x_1', item_type: 'tool', name: 'b', label: 'b', degree: 1 },
          ],
          edges: [{ source: 'x_0', target: 'x_1', kind: 'nonsense', label: 'x', signals: [] }],
          graph_fingerprint: 'x',
        },
      }),
    );
    expect(parsed!.graph.nodes[0].item_type).toBe('tool'); // default
    expect(parsed!.graph.edges[0].kind).toBe('shared_type'); // default
    expect(parsed!.graph.edges[0].directed).toBe(true); // absent → defaults true
  });
});

describe('mcpGraphLegend', () => {
  it('lists only kinds present, in stable order, with counts', () => {
    const graph = mcpInsightGraphFromPayload(graphPayload())!.graph;
    const legend = mcpGraphLegend(graph);
    expect(legend.map((e) => e.kind)).toEqual(['tool', 'resource', 'resource_template', 'prompt']);
    expect(legend.find((e) => e.kind === 'tool')!.count).toBe(1);
    expect(legend.every((e) => e.count > 0)).toBe(true);
  });

  it('omits kinds with no nodes', () => {
    const graph: McpCapabilityGraph = {
      nodes: [{ id: 't_0', item_type: 'tool', name: 'a', title: null, label: 'a', degree: 0 }],
      edges: [],
      node_count: 1,
      edge_count: 0,
      isolated_count: 1,
      graph_fingerprint: 'x',
    };
    expect(mcpGraphLegend(graph).map((e) => e.kind)).toEqual(['tool']);
  });
});

describe('mcpGraphEdgeDisplayLabel', () => {
  const edge = (over: Partial<McpGraphEdge>): McpGraphEdge => ({
    source: 'a',
    target: 'b',
    kind: 'shared_type',
    directed: false,
    label: '',
    signals: [],
    ...over,
  });

  it('shows reference-edge labels verbatim', () => {
    expect(mcpGraphEdgeDisplayLabel(edge({ kind: 'prompt_reference', label: 'search_docs' }))).toBe('search_docs');
    expect(mcpGraphEdgeDisplayLabel(edge({ kind: 'resource_reference', label: 'docs://index' }))).toBe('docs://index');
  });

  it('formats a shared $ref as its tail segment', () => {
    expect(mcpGraphEdgeDisplayLabel(edge({ label: '#/$defs/InvoiceLine' }))).toBe('~ InvoiceLine');
  });

  it('formats a shared title identifier', () => {
    expect(mcpGraphEdgeDisplayLabel(edge({ label: 'title:InvoiceLine' }))).toBe('~ InvoiceLine');
  });
});

describe('mcpGraphToMermaid', () => {
  it('returns null for an empty graph', () => {
    const graph: McpCapabilityGraph = {
      nodes: [],
      edges: [],
      node_count: 0,
      edge_count: 0,
      isolated_count: 0,
      graph_fingerprint: 'x',
    };
    expect(mcpGraphToMermaid(graph)).toBeNull();
  });

  it('emits a flowchart with a classDef per kind, node declarations, and typed connectors', () => {
    const graph = mcpInsightGraphFromPayload(graphPayload())!.graph;
    const src = mcpGraphToMermaid(graph, false)!;
    expect(src.startsWith('flowchart LR')).toBe(true);
    // A classDef per kind, using the light palette.
    expect(src).toContain(`classDef tool fill:${GRAPH_KIND_STYLES.tool.fillLight}`);
    expect(src).toContain('classDef prompt');
    // Node declarations carry the kind class.
    expect(src).toContain('t_0["search_docs"]:::tool');
    expect(src).toContain('p_0["Research"]:::prompt');
    // Directed reference edges render as arrows with a label.
    expect(src).toContain('p_0 -->|"search_docs"| t_0');
    expect(src).toContain('t_0 -->|"docs://index"| r_0');
    // Even the isolated resource_template node is declared.
    expect(src).toContain('rt_0["byid"]:::resource_template');
  });

  it('renders shared_type edges as undirected links with a friendly label', () => {
    const graph: McpCapabilityGraph = {
      nodes: [
        { id: 't_0', item_type: 'tool', name: 'a', title: null, label: 'a', degree: 1 },
        { id: 't_1', item_type: 'tool', name: 'b', title: null, label: 'b', degree: 1 },
      ],
      edges: [
        { source: 't_0', target: 't_1', kind: 'shared_type', directed: false, label: '#/$defs/Filter', signals: ['#/$defs/Filter'] },
      ],
      node_count: 2,
      edge_count: 1,
      isolated_count: 0,
      graph_fingerprint: 'x',
    };
    const src = mcpGraphToMermaid(graph)!;
    expect(src).toContain('t_0 ---|"~ Filter"| t_1');
  });

  it('selects the dark palette when dark=true', () => {
    const graph = mcpInsightGraphFromPayload(graphPayload())!.graph;
    const src = mcpGraphToMermaid(graph, true)!;
    expect(src).toContain(`classDef tool fill:${GRAPH_KIND_STYLES.tool.fillDark}`);
  });

  it('sanitizes labels that contain Mermaid-hostile characters', () => {
    const graph: McpCapabilityGraph = {
      nodes: [
        { id: 't_0', item_type: 'tool', name: 'x', title: null, label: 'a "quoted" | <b> {c} #d', degree: 0 },
      ],
      edges: [],
      node_count: 1,
      edge_count: 0,
      isolated_count: 1,
      graph_fingerprint: 'x',
    };
    const src = mcpGraphToMermaid(graph)!;
    const nodeLine = src.split('\n').find((l) => l.includes('t_0['))!;
    // No raw double-quote, pipe, angle bracket, brace, or hash survives inside the label.
    const inner = nodeLine.slice(nodeLine.indexOf('["') + 2, nodeLine.lastIndexOf('"]'));
    expect(inner).not.toMatch(/["|<>{}#]/);
  });

  it('elides very long labels', () => {
    const longName = 'x'.repeat(80);
    const graph: McpCapabilityGraph = {
      nodes: [{ id: 't_0', item_type: 'tool', name: longName, title: null, label: longName, degree: 0 }],
      edges: [],
      node_count: 1,
      edge_count: 0,
      isolated_count: 1,
      graph_fingerprint: 'x',
    };
    const src = mcpGraphToMermaid(graph)!;
    const nodeLine = src.split('\n').find((l) => l.includes('t_0['))!;
    const inner = nodeLine.slice(nodeLine.indexOf('["') + 2, nodeLine.lastIndexOf('"]'));
    expect(inner.length).toBeLessThan(longName.length);
    expect(inner.endsWith('…')).toBe(true);
  });
});
