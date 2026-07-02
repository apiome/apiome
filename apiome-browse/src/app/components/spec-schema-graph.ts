import type { Edge, Node } from '@xyflow/react';
import dagre from '@dagrejs/dagre';

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export type BrowseGraphFormat = 'openapi' | 'arazzo' | 'jsonschema';

/** Primary edge flow for Dagre (`auto` keeps the previous per-cluster TB vs LR heuristic). */
export type BrowseLayoutDirection = 'auto' | 'TB' | 'BT' | 'LR' | 'RL';

/** Vertical / horizontal gap between nodes — tweak for readability on dense graphs. */
export type BrowseLayoutDensity = 'compact' | 'default' | 'spacious';

export interface BrowseLayoutOptions {
  direction: BrowseLayoutDirection;
  density: BrowseLayoutDensity;
}

export const DEFAULT_BROWSE_LAYOUT: BrowseLayoutOptions = {
  direction: 'auto',
  density: 'default',
};

export const BROWSE_LAYOUT_DIRECTION_LABELS: Record<BrowseLayoutDirection, string> = {
  auto: 'Auto',
  TB: 'Top → bottom',
  BT: 'Bottom → top',
  LR: 'Left → right',
  RL: 'Right → left',
};

export const BROWSE_LAYOUT_DENSITY_LABELS: Record<BrowseLayoutDensity, string> = {
  compact: 'Compact',
  default: 'Balanced',
  spacious: 'Spacious',
};

function mergeBrowseLayoutOptions(partial?: Partial<BrowseLayoutOptions>): BrowseLayoutOptions {
  return {
    direction: partial?.direction ?? DEFAULT_BROWSE_LAYOUT.direction,
    density: partial?.density ?? DEFAULT_BROWSE_LAYOUT.density,
  };
}

export interface BrowseSpecGraphResult {
  nodes: Node[];
  edges: Edge[];
  /** True when the format supports schema graphs but there is nothing to draw */
  isEmpty: boolean;
  /** Message when visual is unavailable (e.g. Arazzo) */
  unavailableReason?: string;
}

const NODE_WIDTH = 220;
const NODE_HEIGHT = 76;

function decodePointerSegment(seg: string): string {
  try {
    return decodeURIComponent(seg.replace(/~1/g, '/').replace(/~0/g, '~'));
  } catch {
    return seg;
  }
}

/** Resolve internal JSON Pointer refs to a local schema name in this document. */
export function resolveLocalRefName(ref: string): string | null {
  if (!ref.startsWith('#')) return null;
  const frag = ref.slice(1);
  const tail = frag.startsWith('/') ? frag.slice(1) : frag;
  const segments = tail.split('/').filter(Boolean).map(decodePointerSegment);
  if (segments.length < 2) return null;

  if (segments[0] === 'components' && segments[1] === 'schemas') {
    const name = segments.slice(2).join('/');
    return name || null;
  }
  if (segments[0] === 'definitions') {
    const name = segments.slice(1).join('/');
    return name || null;
  }
  if (segments[0] === '$defs') {
    const name = segments.slice(1).join('/');
    return name || null;
  }
  return null;
}

type EdgeKind = 'allOf' | 'anyOf' | 'oneOf' | 'ref';

interface DraftEdge {
  source: string;
  target: string;
  kind: EdgeKind;
  /** Dot-path for ref-style edges (property / items), empty for composition-only */
  path: string;
}

function walkRefEdges(
  source: string,
  value: unknown,
  known: Set<string>,
  resolveRef: (ref: string) => string | null,
  edges: DraftEdge[],
  immediateComposition: 'allOf' | 'anyOf' | 'oneOf' | null,
  propPath: string[],
  depth: number
): void {
  if (depth > 32) return;
  if (!isObject(value)) return;

  if (typeof value.$ref === 'string') {
    const target = resolveRef(value.$ref);
    if (target && known.has(target)) {
      edges.push({
        source,
        target,
        kind: immediateComposition ?? 'ref',
        path: propPath.join('.'),
      });
    }
    return;
  }

  for (const key of ['allOf', 'anyOf', 'oneOf'] as const) {
    const arr = value[key];
    if (!Array.isArray(arr)) continue;
    for (const item of arr) {
      walkRefEdges(source, item, known, resolveRef, edges, key, propPath, depth + 1);
    }
  }

  const props = value.properties;
  if (isObject(props)) {
    for (const [name, sub] of Object.entries(props)) {
      walkRefEdges(source, sub, known, resolveRef, edges, null, [...propPath, name], depth + 1);
    }
  }

  if (value.items !== undefined) {
    walkRefEdges(source, value.items, known, resolveRef, edges, null, [...propPath, 'items'], depth + 1);
  }

  const addl = value.additionalProperties;
  if (addl === true || addl === false) {
    /* scalar */
  } else if (isObject(addl)) {
    walkRefEdges(source, addl, known, resolveRef, edges, null, [...propPath, 'additionalProperties'], depth + 1);
  }
}

function draftEdgeKey(d: DraftEdge): string {
  return `${d.source}|${d.target}|${d.kind}|${d.path}`;
}

function edgeStyle(kind: EdgeKind, dark: boolean): {
  stroke: string;
  strokeDasharray?: string;
  labelStyle: { fill: string; fontSize: number; fontWeight: number };
} {
  if (dark) {
    switch (kind) {
      case 'allOf':
        return {
          stroke: '#60a5fa',
          labelStyle: { fill: '#93c5fd', fontSize: 11, fontWeight: 600 },
        };
      case 'anyOf':
        return {
          stroke: '#fb923c',
          strokeDasharray: '6 4',
          labelStyle: { fill: '#fdba74', fontSize: 11, fontWeight: 600 },
        };
      case 'oneOf':
        return {
          stroke: '#c084fc',
          strokeDasharray: '2 5',
          labelStyle: { fill: '#d8b4fe', fontSize: 11, fontWeight: 600 },
        };
      default:
        return {
          stroke: '#94a3b8',
          labelStyle: { fill: '#cbd5e1', fontSize: 11, fontWeight: 500 },
        };
    }
  }
  switch (kind) {
    case 'allOf':
      return {
        stroke: '#2563eb',
        labelStyle: { fill: '#1d4ed8', fontSize: 11, fontWeight: 600 },
      };
    case 'anyOf':
      return {
        stroke: '#ea580c',
        strokeDasharray: '6 4',
        labelStyle: { fill: '#c2410c', fontSize: 11, fontWeight: 600 },
      };
    case 'oneOf':
      return {
        stroke: '#9333ea',
        strokeDasharray: '2 5',
        labelStyle: { fill: '#7e22ce', fontSize: 11, fontWeight: 600 },
      };
    default:
      return {
        stroke: '#64748b',
        labelStyle: { fill: '#475569', fontSize: 11, fontWeight: 500 },
      };
  }
}

function formatPathLabel(path: string): string {
  if (!path) return '';
  return path.replace(/\.items/g, '[]');
}

function draftToRfEdges(drafts: DraftEdge[], dark: boolean): Edge[] {
  const seen = new Set<string>();
  const out: Edge[] = [];
  let i = 0;
  for (const d of drafts) {
    const key = draftEdgeKey(d);
    if (seen.has(key)) continue;
    seen.add(key);
    const { stroke, strokeDasharray, labelStyle } = edgeStyle(d.kind, dark);
    const pathSuffix = formatPathLabel(d.path);
    let label: string;
    if (d.kind === 'ref') {
      label = pathSuffix ? pathSuffix : '$ref';
    } else {
      label = pathSuffix ? `${d.kind} · ${pathSuffix}` : d.kind;
    }
    out.push({
      id: `e-${d.source}-${d.target}-${d.kind}-${i++}`,
      source: d.source,
      target: d.target,
      label,
      animated: false,
      style: { stroke, strokeWidth: 2, strokeDasharray },
      markerEnd: { type: 'arrowclosed', color: stroke, width: 16, height: 16 },
      labelStyle,
      labelBgStyle: dark ? { fill: '#18181b', fillOpacity: 0.92 } : { fill: '#ffffff', fillOpacity: 0.95 },
      labelBgPadding: [4, 2] as [number, number],
    });
  }
  return out;
}

function collectOpenApiSchemaMap(spec: Record<string, unknown>): Map<string, Record<string, unknown>> {
  const map = new Map<string, Record<string, unknown>>();
  const components = isObject(spec.components) ? spec.components : null;
  const componentSchemas = components && isObject(components.schemas) ? components.schemas : {};
  const legacyDefinitions = isObject(spec.definitions) ? spec.definitions : {};
  for (const [k, v] of Object.entries(componentSchemas)) {
    if (isObject(v)) map.set(k, v);
  }
  for (const [k, v] of Object.entries(legacyDefinitions)) {
    if (isObject(v) && !map.has(k)) map.set(k, v);
  }
  return map;
}

function extractJsonSchemaRootFragment(spec: Record<string, unknown>): Record<string, unknown> | null {
  const { $defs: _d, definitions: _def, ...rest } = spec;
  void _d;
  void _def;
  if (
    typeof rest.$ref === 'string' ||
    isObject(rest.properties) ||
    Array.isArray(rest.allOf) ||
    Array.isArray(rest.anyOf) ||
    Array.isArray(rest.oneOf) ||
    rest.items !== undefined
  ) {
    return rest;
  }
  return null;
}

function collectJsonSchemaMap(spec: Record<string, unknown>): Map<string, Record<string, unknown>> {
  const map = new Map<string, Record<string, unknown>>();
  const defs =
    (isObject(spec.$defs) ? spec.$defs : null) ||
    (isObject(spec.definitions) ? spec.definitions : null);
  if (defs) {
    for (const [k, v] of Object.entries(defs)) {
      if (isObject(v)) map.set(k, v);
    }
  }
  const rootFrag = extractJsonSchemaRootFragment(spec);
  if (rootFrag) {
    map.set('__root__', rootFrag);
  }
  return map;
}

function connectedComponents(nodeIds: string[], edges: Pick<Edge, 'source' | 'target'>[]): string[][] {
  const adj = new Map<string, string[]>();
  for (const id of nodeIds) adj.set(id, []);
  for (const e of edges) {
    const a = adj.get(e.source);
    const b = adj.get(e.target);
    if (a && b) {
      a.push(e.target);
      b.push(e.source);
    }
  }

  const visited = new Set<string>();
  const out: string[][] = [];
  for (const id of nodeIds) {
    if (visited.has(id)) continue;
    const comp: string[] = [];
    const stack = [id];
    visited.add(id);
    while (stack.length > 0) {
      const u = stack.pop()!;
      comp.push(u);
      for (const v of adj.get(u) ?? []) {
        if (!visited.has(v)) {
          visited.add(v);
          stack.push(v);
        }
      }
    }
    out.push(comp);
  }
  return out;
}

function bboxOfLayout(nodes: Pick<Node, 'position'>[]): { minX: number; minY: number; maxX: number; maxY: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.position.x);
    minY = Math.min(minY, n.position.y);
    maxX = Math.max(maxX, n.position.x + NODE_WIDTH);
    maxY = Math.max(maxY, n.position.y + NODE_HEIGHT);
  }
  if (!Number.isFinite(minX)) {
    return { minX: 0, minY: 0, maxX: NODE_WIDTH, maxY: NODE_HEIGHT };
  }
  return { minX, minY, maxX, maxY };
}

const DENSITY_SCALE: Record<
  BrowseLayoutDensity,
  { nodesep: number; ranksep: number; margin: number; edgesep: number }
> = {
  compact: { nodesep: 0.74, ranksep: 0.8, margin: 0.88, edgesep: 0.85 },
  default: { nodesep: 1, ranksep: 1, margin: 1, edgesep: 1 },
  spacious: { nodesep: 1.38, ranksep: 1.45, margin: 1.18, edgesep: 1.12 },
};

function resolveRankdir(
  n: number,
  avgDegree: number,
  direction: BrowseLayoutDirection
): 'TB' | 'BT' | 'LR' | 'RL' {
  if (direction !== 'auto') return direction;
  return n >= 26 || avgDegree >= 3.2 ? 'LR' : 'TB';
}

/** Dagre on one subgraph; rank direction and gaps come from layout options + graph size. */
function layoutSubgraphWithDagre(nodes: Node[], edges: Edge[], layout: BrowseLayoutOptions): Node[] {
  if (nodes.length === 0) return nodes;

  const n = nodes.length;
  const m = edges.length;
  const avgDegree = n > 0 ? (2 * m) / n : 0;
  const rankdir = resolveRankdir(n, avgDegree, layout.direction);
  const scale = DENSITY_SCALE[layout.density];

  let nodesep = Math.round(Math.min(112, Math.max(44, 36 + Math.sqrt(n) * 7)) * scale.nodesep);
  let ranksep = Math.round(Math.min(180, Math.max(52, 46 + avgDegree * 14)) * scale.ranksep);
  let margin = Math.round(Math.min(96, Math.max(40, 28 + n * 0.45)) * scale.margin);
  let edgesep = Math.round(Math.min(52, Math.max(18, 14 + m / Math.max(n, 1))) * scale.edgesep);

  nodesep = Math.max(28, nodesep);
  ranksep = Math.max(36, ranksep);
  margin = Math.max(24, margin);
  edgesep = Math.max(12, edgesep);

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir,
    nodesep,
    ranksep,
    marginx: margin,
    marginy: margin,
    ranker: 'network-simplex',
    edgesep,
  });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of edges) {
    if (g.hasNode(e.source) && g.hasNode(e.target)) {
      g.setEdge(e.source, e.target);
    }
  }

  dagre.layout(g);

  return nodes.map((node) => {
    const pos = g.node(node.id);
    if (!pos) return { ...node, position: { x: 0, y: 0 } };
    return {
      ...node,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
    };
  });
}

/**
 * Hierarchical auto-layout: each connected component is laid out with Dagre (tuned for size),
 * then components are packed in rows so disjoint schema clusters do not overlap — important for
 * large OpenAPI documents with many independent models.
 */
export function layoutSpecSchemaNodes(
  nodes: Node[],
  edges: Edge[],
  layoutPartial?: Partial<BrowseLayoutOptions>
): Node[] {
  if (nodes.length === 0) return nodes;

  const layout = mergeBrowseLayoutOptions(layoutPartial);

  const nodeIds = nodes.map((n) => n.id);
  const components = connectedComponents(nodeIds, edges);
  components.sort((a, b) => b.length - a.length);

  const gapScale = DENSITY_SCALE[layout.density].margin;
  const PACK_GAP_X = Math.round(72 * gapScale);
  const PACK_GAP_Y = Math.round(72 * gapScale);
  /** Start a new row once the packed width exceeds this (keeps rows usable on typical viewports). */
  const baseRow = Math.min(3400, Math.max(1600, 520 + nodes.length * 28));
  const maxPackRowWidth = Math.round(
    layout.direction === 'LR' || layout.direction === 'RL' ? baseRow * 1.08 : baseRow
  );

  let originX = 0;
  let originY = 0;
  let rowHeight = 0;
  const placed: Node[] = [];

  for (const comp of components) {
    const idSet = new Set(comp);
    const subNodes = nodes
      .filter((node) => idSet.has(node.id))
      .map((node) => ({ ...node, position: { x: 0, y: 0 } }));
    const subEdges = edges.filter((e) => idSet.has(e.source) && idSet.has(e.target));

    const laidOut = layoutSubgraphWithDagre(subNodes, subEdges, layout);
    const bb = bboxOfLayout(laidOut);
    const pieceW = bb.maxX - bb.minX;
    const pieceH = bb.maxY - bb.minY;

    if (originX > 0 && originX + pieceW > maxPackRowWidth) {
      originX = 0;
      originY += rowHeight + PACK_GAP_Y;
      rowHeight = 0;
    }

    const dx = originX - bb.minX;
    const dy = originY - bb.minY;
    for (const node of laidOut) {
      placed.push({
        ...node,
        position: { x: node.position.x + dx, y: node.position.y + dy },
      });
    }

    originX += pieceW + PACK_GAP_X;
    rowHeight = Math.max(rowHeight, pieceH);
  }

  const orderIndex = new Map(nodes.map((node, i) => [node.id, i]));
  placed.sort((a, b) => (orderIndex.get(a.id) ?? 0) - (orderIndex.get(b.id) ?? 0));

  return placed;
}

export function buildBrowseSpecSchemaGraph(
  spec: unknown,
  format: BrowseGraphFormat,
  dark: boolean,
  layoutPartial?: Partial<BrowseLayoutOptions>
): BrowseSpecGraphResult {
  const layoutOpts = mergeBrowseLayoutOptions(layoutPartial);
  if (format === 'arazzo') {
    return {
      nodes: [],
      edges: [],
      isEmpty: true,
      unavailableReason:
        'Visual schema graphs apply to OpenAPI and JSON Schema documents. Arazzo workflows do not expose component schemas here.',
    };
  }

  if (!isObject(spec)) {
    return { nodes: [], edges: [], isEmpty: true };
  }

  const schemaMap =
    format === 'openapi' ? collectOpenApiSchemaMap(spec) : collectJsonSchemaMap(spec);

  if (schemaMap.size === 0) {
    return {
      nodes: [],
      edges: [],
      isEmpty: true,
      unavailableReason:
        format === 'openapi'
          ? 'No schemas found under components.schemas or definitions.'
          : 'No reusable schemas found under $defs / definitions (and no composable root schema).',
    };
  }

  const known = new Set(schemaMap.keys());

  const resolveRef = (ref: string): string | null => {
    const name = resolveLocalRefName(ref);
    return name && known.has(name) ? name : null;
  };

  const drafts: DraftEdge[] = [];
  for (const [name, schema] of schemaMap.entries()) {
    walkRefEdges(name, schema, known, resolveRef, drafts, null, [], 0);
  }

  const nodes: Node[] = [];
  for (const name of schemaMap.keys()) {
    const schema = schemaMap.get(name)!;

    if (name === '__root__') {
      const rootTitle =
        isObject(schema) && typeof schema.title === 'string'
          ? schema.title
          : typeof (spec as Record<string, unknown>).title === 'string'
            ? ((spec as Record<string, unknown>).title as string)
            : undefined;
      nodes.push({
        id: name,
        type: 'specSchema',
        position: { x: 0, y: 0 },
        data: {
          label: rootTitle ?? 'Root',
          subtitle: 'Root schema',
          mono: false,
        },
      });
      continue;
    }

    const title = isObject(schema) && typeof schema.title === 'string' ? schema.title : undefined;
    nodes.push({
      id: name,
      type: 'specSchema',
      position: { x: 0, y: 0 },
      data: {
        label: name,
        subtitle: title,
        mono: true,
      },
    });
  }

  const edges = draftToRfEdges(drafts, dark);
  const layouted = layoutSpecSchemaNodes(nodes, edges, layoutOpts);

  return {
    nodes: layouted,
    edges,
    isEmpty: layouted.length === 0,
  };
}
