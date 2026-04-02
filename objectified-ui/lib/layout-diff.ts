/**
 * Layout diff utility for comparing canvas layout states.
 * Detects additions, removals, and modifications in nodes, edges,
 * viewport, and settings between two layout snapshots.
 */

export type LayoutDiffChangeType = 'added' | 'removed' | 'modified' | 'unchanged';
export type LayoutDiffCategory = 'node' | 'edge' | 'viewport' | 'grid' | 'minimap';

export interface LayoutDiffEntry {
  type: LayoutDiffChangeType;
  category: LayoutDiffCategory;
  id: string;
  label: string;
  changes?: string[];
  oldValue?: unknown;
  newValue?: unknown;
}

export interface LayoutDiffSummary {
  nodes: {
    added: LayoutDiffEntry[];
    removed: LayoutDiffEntry[];
    modified: LayoutDiffEntry[];
    unchanged: number;
  };
  edges: {
    added: LayoutDiffEntry[];
    removed: LayoutDiffEntry[];
    modified: LayoutDiffEntry[];
    unchanged: number;
  };
  viewport: LayoutDiffEntry | null;
  gridSettings: LayoutDiffEntry | null;
  minimapSettings: LayoutDiffEntry | null;
  totalChanges: number;
}

interface LayoutNode {
  id: string;
  type?: string;
  position?: { x: number; y: number };
  dimensions?: { width?: string | number; height?: string | number };
  data?: Record<string, unknown>;
}

interface LayoutEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

interface LayoutViewport {
  x?: number;
  y?: number;
  zoom?: number;
}

export interface LayoutState {
  viewport?: LayoutViewport | null;
  nodes?: LayoutNode[] | null;
  edges?: LayoutEdge[] | null;
  grid_settings?: Record<string, unknown> | null;
  minimap_settings?: Record<string, unknown> | null;
}

const POSITION_THRESHOLD = 0.5;

function safeArray<T>(arr: T[] | null | undefined): T[] {
  return Array.isArray(arr) ? arr : [];
}

function nodeLabel(node: LayoutNode): string {
  const name = typeof node.data?.name === 'string' ? node.data.name : undefined;
  return name || node.id;
}

function positionChanged(a: LayoutNode['position'], b: LayoutNode['position']): boolean {
  if (!a && !b) return false;
  if (!a || !b) return true;
  return (
    Math.abs((a.x ?? 0) - (b.x ?? 0)) > POSITION_THRESHOLD ||
    Math.abs((a.y ?? 0) - (b.y ?? 0)) > POSITION_THRESHOLD
  );
}

function toDimensionNum(v: string | number | undefined): number {
  if (v === undefined || v === null) return 0;
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return Number.isFinite(n) ? n : 0;
}

function dimensionsChanged(a: LayoutNode['dimensions'], b: LayoutNode['dimensions']): boolean {
  if (!a && !b) return false;
  if (!a || !b) return true;
  return (
    toDimensionNum(a.width) !== toDimensionNum(b.width) ||
    toDimensionNum(a.height) !== toDimensionNum(b.height)
  );
}

function compareNodes(leftNodes: LayoutNode[], rightNodes: LayoutNode[]) {
  const leftMap = new Map(leftNodes.map((n) => [n.id, n]));
  const rightMap = new Map(rightNodes.map((n) => [n.id, n]));

  const added: LayoutDiffEntry[] = [];
  const removed: LayoutDiffEntry[] = [];
  const modified: LayoutDiffEntry[] = [];
  let unchanged = 0;

  for (const [id, node] of rightMap) {
    if (!leftMap.has(id)) {
      added.push({
        type: 'added',
        category: 'node',
        id,
        label: nodeLabel(node),
        newValue: node,
      });
    }
  }

  for (const [id, node] of leftMap) {
    if (!rightMap.has(id)) {
      removed.push({
        type: 'removed',
        category: 'node',
        id,
        label: nodeLabel(node),
        oldValue: node,
      });
    }
  }

  for (const [id, leftNode] of leftMap) {
    const rightNode = rightMap.get(id);
    if (!rightNode) continue;

    const changes: string[] = [];

    if (leftNode.type !== rightNode.type) {
      changes.push('type');
    }
    if (positionChanged(leftNode.position, rightNode.position)) {
      changes.push('position');
    }
    if (dimensionsChanged(leftNode.dimensions, rightNode.dimensions)) {
      changes.push('dimensions');
    }
    if (
      leftNode.data &&
      rightNode.data &&
      JSON.stringify(leftNode.data) !== JSON.stringify(rightNode.data)
    ) {
      changes.push('data');
    }

    if (changes.length > 0) {
      modified.push({
        type: 'modified',
        category: 'node',
        id,
        label: nodeLabel(leftNode),
        changes,
        oldValue: leftNode,
        newValue: rightNode,
      });
    } else {
      unchanged++;
    }
  }

  return { added, removed, modified, unchanged };
}

function edgeLabel(edge: LayoutEdge): string {
  return `${edge.source} → ${edge.target}`;
}

function compareEdges(leftEdges: LayoutEdge[], rightEdges: LayoutEdge[]) {
  const leftMap = new Map(leftEdges.map((e) => [e.id, e]));
  const rightMap = new Map(rightEdges.map((e) => [e.id, e]));

  const added: LayoutDiffEntry[] = [];
  const removed: LayoutDiffEntry[] = [];
  const modified: LayoutDiffEntry[] = [];
  let unchanged = 0;

  for (const [id, edge] of rightMap) {
    if (!leftMap.has(id)) {
      added.push({
        type: 'added',
        category: 'edge',
        id,
        label: edgeLabel(edge),
        newValue: edge,
      });
    }
  }

  for (const [id, edge] of leftMap) {
    if (!rightMap.has(id)) {
      removed.push({
        type: 'removed',
        category: 'edge',
        id,
        label: edgeLabel(edge),
        oldValue: edge,
      });
    }
  }

  for (const [id, leftEdge] of leftMap) {
    const rightEdge = rightMap.get(id);
    if (!rightEdge) continue;

    const changes: string[] = [];

    if (leftEdge.source !== rightEdge.source) changes.push('source');
    if (leftEdge.target !== rightEdge.target) changes.push('target');
    if ((leftEdge.sourceHandle ?? null) !== (rightEdge.sourceHandle ?? null))
      changes.push('sourceHandle');
    if ((leftEdge.targetHandle ?? null) !== (rightEdge.targetHandle ?? null))
      changes.push('targetHandle');

    if (changes.length > 0) {
      modified.push({
        type: 'modified',
        category: 'edge',
        id,
        label: edgeLabel(leftEdge),
        changes,
        oldValue: leftEdge,
        newValue: rightEdge,
      });
    } else {
      unchanged++;
    }
  }

  return { added, removed, modified, unchanged };
}

function compareViewport(
  left: LayoutViewport | null | undefined,
  right: LayoutViewport | null | undefined
): LayoutDiffEntry | null {
  const l = left ?? {};
  const r = right ?? {};

  const changes: string[] = [];
  if (Math.abs((l.x ?? 0) - (r.x ?? 0)) > POSITION_THRESHOLD) changes.push('x');
  if (Math.abs((l.y ?? 0) - (r.y ?? 0)) > POSITION_THRESHOLD) changes.push('y');
  if ((l.zoom ?? 1) !== (r.zoom ?? 1)) changes.push('zoom');

  if (changes.length === 0) return null;

  return {
    type: 'modified',
    category: 'viewport',
    id: 'viewport',
    label: 'Viewport',
    changes,
    oldValue: l,
    newValue: r,
  };
}

function compareSettings(
  left: Record<string, unknown> | null | undefined,
  right: Record<string, unknown> | null | undefined,
  category: 'grid' | 'minimap'
): LayoutDiffEntry | null {
  const lStr = JSON.stringify(left ?? {});
  const rStr = JSON.stringify(right ?? {});
  if (lStr === rStr) return null;

  const l = left ?? {};
  const r = right ?? {};
  const allKeys = new Set([...Object.keys(l), ...Object.keys(r)]);
  const changes: string[] = [];

  for (const key of allKeys) {
    if (JSON.stringify(l[key]) !== JSON.stringify(r[key])) {
      changes.push(key);
    }
  }

  if (changes.length === 0) return null;

  const label = category === 'grid' ? 'Grid settings' : 'Minimap settings';
  return {
    type: 'modified',
    category,
    id: category,
    label,
    changes,
    oldValue: l,
    newValue: r,
  };
}

/**
 * Compare two canvas layout states and return a structured diff summary.
 */
export function compareLayouts(left: LayoutState, right: LayoutState): LayoutDiffSummary {
  const nodes = compareNodes(safeArray(left.nodes), safeArray(right.nodes));
  const edges = compareEdges(safeArray(left.edges), safeArray(right.edges));
  const viewport = compareViewport(left.viewport, right.viewport);
  const gridSettings = compareSettings(left.grid_settings, right.grid_settings, 'grid');
  const minimapSettings = compareSettings(left.minimap_settings, right.minimap_settings, 'minimap');

  const totalChanges =
    nodes.added.length +
    nodes.removed.length +
    nodes.modified.length +
    edges.added.length +
    edges.removed.length +
    edges.modified.length +
    (viewport ? 1 : 0) +
    (gridSettings ? 1 : 0) +
    (minimapSettings ? 1 : 0);

  return {
    nodes,
    edges,
    viewport,
    gridSettings,
    minimapSettings,
    totalChanges,
  };
}

/**
 * Collect all diff entries from a summary into a flat list,
 * ordered by category (nodes, edges, viewport, settings).
 */
export function flattenDiffEntries(summary: LayoutDiffSummary): LayoutDiffEntry[] {
  const entries: LayoutDiffEntry[] = [
    ...summary.nodes.added,
    ...summary.nodes.removed,
    ...summary.nodes.modified,
    ...summary.edges.added,
    ...summary.edges.removed,
    ...summary.edges.modified,
  ];
  if (summary.viewport) entries.push(summary.viewport);
  if (summary.gridSettings) entries.push(summary.gridSettings);
  if (summary.minimapSettings) entries.push(summary.minimapSettings);
  return entries;
}
