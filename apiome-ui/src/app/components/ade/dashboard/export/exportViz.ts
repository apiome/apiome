/**
 * Export visualization modes — the views an emitted artifact can be drawn as (MFX-45.4, #4377).
 *
 * Which pictures a target has is **registry data**: the target's descriptor lists its `viz_modes`
 * (`GET /export/targets`, declared by the emitter like its test-drive tools), and the export preview
 * manifest carries each mode's data — `relational` for the `erd`, `views[mode]` for the graph modes.
 * Nothing here names a format:
 *
 *  - {@link availableVizModes}: the declared modes that have something to draw;
 *  - {@link loadVizChoice} / {@link saveVizChoice}: the view chosen for a target, kept for the session;
 *  - {@link vizGraphLayout}: a deterministic column layout of any mode's graph — a node one column right
 *    of the furthest node pointing at it (services → methods → messages, operations → channels →
 *    messages, importing file → imported file);
 *  - {@link vizSelection}: which nodes the Review step's entity selection highlights.
 *
 * Everything here is pure except the two storage helpers, which never throw.
 */

import type { RelationalSchema } from './exportErd';

/** The four modes (mirror of REST `ExportVizModeKind`). */
export type ExportVizModeKind = 'erd' | 'proto-imports' | 'service-map' | 'channel-topology';

/** One declared mode (mirror of REST `ExportVizMode`). */
export interface ExportVizMode {
  kind: ExportVizModeKind;
  /** The view switch label, e.g. `Import graph`. */
  label: string;
}

/** One node of a mode's graph (mirror of REST `VizNode`). */
export interface VizNode {
  id: string;
  label: string;
  /** `file`, `service`, `method`, `message`, `channel`, `operation`, `message-group`, `event-type`. */
  kind: string;
  detail?: string | null;
  /** Referenced by the artifact but not held by it (a well-known import). */
  external?: boolean;
  file?: string | null;
  line?: number | null;
  /** The canonical construct the node stands for. */
  entity_key?: string | null;
}

/** One edge of a mode's graph (mirror of REST `VizEdge`). */
export interface VizEdge {
  id: string;
  source: string;
  target: string;
  /** `import`, `method`, `request`, `response`, `carries`, `uses`, `sends`, `receives`, `contains`, `typed`. */
  kind: string;
  label?: string | null;
}

/** A mode's graph (mirror of REST `VizGraph`). */
export interface VizGraph {
  mode: ExportVizModeKind;
  nodes: VizNode[];
  edges: VizEdge[];
}

/** The view a viewer shows: the text, or one of the target's modes. */
export type ArtifactView = 'text' | ExportVizModeKind;

// ---------------------------------------------------------------------------
// Availability
// ---------------------------------------------------------------------------

/** The data the modes draw, as the preview manifest carries it. */
export interface VizData {
  relational?: RelationalSchema | null;
  views?: Record<string, VizGraph> | null;
}

/** The default label of a mode when only its data, not its declaration, is known. */
const MODE_LABELS: Record<ExportVizModeKind, string> = {
  erd: 'ERD',
  'proto-imports': 'Import graph',
  'service-map': 'Service map',
  'channel-topology': 'Channel topology',
};

/** Whether `mode` has something to draw in `data`. */
function hasData(mode: ExportVizModeKind, data: VizData): boolean {
  if (mode === 'erd') return (data.relational?.tables.length ?? 0) > 0;
  return (data.views?.[mode]?.nodes.length ?? 0) > 0;
}

/**
 * The modes a viewer offers: every declared mode with something to draw, in declared order. With no
 * declaration (an older server, or a caller that has none), the modes are those the data holds.
 *
 * @param declared The target descriptor's `viz_modes`, or undefined when unknown.
 * @param data The manifest's `relational` and `views`.
 * @returns The modes to offer beside the text.
 */
export function availableVizModes(declared: ExportVizMode[] | null | undefined, data: VizData): ExportVizMode[] {
  if (declared) return declared.filter((mode) => hasData(mode.kind, data));
  const inferred: ExportVizMode[] = [];
  if (hasData('erd', data)) inferred.push({ kind: 'erd', label: MODE_LABELS.erd });
  for (const [kind, graph] of Object.entries(data.views ?? {})) {
    if (kind in MODE_LABELS && kind !== 'erd' && graph.nodes.length > 0) {
      inferred.push({ kind: kind as ExportVizModeKind, label: MODE_LABELS[kind as ExportVizModeKind] });
    }
  }
  return inferred;
}

// ---------------------------------------------------------------------------
// The chosen view, per target, for the session
// ---------------------------------------------------------------------------

/** The session-storage key of a target's chosen view. */
export function vizChoiceKey(targetKey: string): string {
  return `apiome.export.view.${targetKey}`;
}

/**
 * The view last chosen for `targetKey` this session, if it is still offered; else the text.
 *
 * @param targetKey The export target's key.
 * @param modes The modes offered now.
 * @returns The view to start on.
 */
export function loadVizChoice(targetKey: string | null | undefined, modes: ExportVizMode[]): ArtifactView {
  if (!targetKey) return 'text';
  try {
    const stored = window.sessionStorage.getItem(vizChoiceKey(targetKey));
    if (stored && modes.some((mode) => mode.kind === stored)) return stored as ExportVizModeKind;
  } catch {
    // Storage blocked (a private window, a sandbox): start on the text.
  }
  return 'text';
}

/**
 * Remember the view chosen for `targetKey` for the session (silently a no-op when storage is blocked).
 *
 * @param targetKey The export target's key.
 * @param view The chosen view.
 */
export function saveVizChoice(targetKey: string | null | undefined, view: ArtifactView): void {
  if (!targetKey) return;
  try {
    window.sessionStorage.setItem(vizChoiceKey(targetKey), view);
  } catch {
    // Storage blocked: the choice lasts as long as the viewer.
  }
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

/** Geometry of a graph mode's drawing. */
export const VIZ_GEOMETRY = {
  nodeWidth: 240,
  nodeHeight: 56,
  columnGap: 120,
  rowGap: 20,
} as const;

/** One placed node. */
export interface PlacedVizNode {
  node: VizNode;
  column: number;
  x: number;
  y: number;
}

/**
 * Each node's column: 0 for a node no edge points at, else one more than the furthest node pointing at
 * it. Cycles are cut where the walk re-enters them.
 *
 * @param graph The graph.
 * @returns Node id → column.
 */
export function vizColumns(graph: VizGraph): Map<string, number> {
  const incoming = new Map<string, string[]>();
  for (const edge of graph.edges) {
    if (edge.source === edge.target) continue;
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
  }
  const columns = new Map<string, number>();
  const visiting = new Set<string>();
  const columnOf = (id: string): number => {
    const known = columns.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    let column = 0;
    for (const source of incoming.get(id) ?? []) column = Math.max(column, columnOf(source) + 1);
    visiting.delete(id);
    columns.set(id, column);
    return column;
  };
  for (const node of graph.nodes) columnOf(node.id);
  return columns;
}

/**
 * Lay a graph out in columns ({@link vizColumns}), nodes stacked in each column in graph order.
 *
 * @param graph The graph.
 * @returns The placed nodes, in graph order.
 */
export function vizGraphLayout(graph: VizGraph): PlacedVizNode[] {
  const columns = vizColumns(graph);
  const rows = new Map<number, number>();
  return graph.nodes.map((node) => {
    const column = columns.get(node.id) ?? 0;
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    return {
      node,
      column,
      x: column * (VIZ_GEOMETRY.nodeWidth + VIZ_GEOMETRY.columnGap),
      y: row * (VIZ_GEOMETRY.nodeHeight + VIZ_GEOMETRY.rowGap),
    };
  });
}

// ---------------------------------------------------------------------------
// Selection, counts and labels
// ---------------------------------------------------------------------------

/**
 * The ids of the nodes that stand for the selected construct.
 *
 * @param graph The graph.
 * @param entityKey The selected construct, or null.
 * @returns The matching node ids (empty with nothing selected).
 */
export function vizSelection(graph: VizGraph, entityKey: string | null): Set<string> {
  if (!entityKey) return new Set();
  return new Set(graph.nodes.filter((node) => node.entity_key === entityKey).map((node) => node.id));
}

/** Words for a node kind, singular and plural. */
const NODE_KIND_WORDS: Record<string, [string, string]> = {
  file: ['file', 'files'],
  service: ['service', 'services'],
  method: ['method', 'methods'],
  message: ['message', 'messages'],
  channel: ['channel', 'channels'],
  operation: ['operation', 'operations'],
  'message-group': ['message group', 'message groups'],
  'event-type': ['event type', 'event types'],
};

/** The word for a node kind (`message group`), falling back to the kind itself. */
export function nodeKindLabel(kind: string, count = 1): string {
  const words = NODE_KIND_WORDS[kind];
  if (!words) return kind;
  return count === 1 ? words[0] : words[1];
}

/**
 * The summary of a graph: how many of each node kind, in first-seen order (`3 files · 2 external`).
 *
 * @param graph The graph.
 * @returns The summary line.
 */
export function vizSummary(graph: VizGraph): string {
  const counts = new Map<string, number>();
  for (const node of graph.nodes) counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1);
  const parts = [...counts].map(([kind, count]) => `${count} ${nodeKindLabel(kind, count)}`);
  const external = graph.nodes.filter((node) => node.external).length;
  if (external > 0) parts.push(`${external} external`);
  return parts.join(' · ');
}

/**
 * The accessible name of a node: its kind, label, detail, and whether it is external or selectable.
 *
 * @param node The node.
 * @returns e.g. `Method WatchOrders, server stream`.
 */
export function vizNodeAriaLabel(node: VizNode): string {
  const kind = nodeKindLabel(node.kind);
  const parts = [`${kind.charAt(0).toUpperCase()}${kind.slice(1)} ${node.label}`];
  if (node.detail) parts.push(node.detail);
  if (node.external) parts.push('not in this export');
  return parts.join(', ');
}

/** The visible label of an edge: its own label (`stream`), else its kind for the kinds worth naming. */
export function vizEdgeLabel(edge: VizEdge): string | undefined {
  if (edge.label) return edge.kind === 'request' || edge.kind === 'response' ? `${edge.kind} · ${edge.label}` : edge.label;
  if (edge.kind === 'request' || edge.kind === 'response' || edge.kind === 'sends' || edge.kind === 'receives') {
    return edge.kind;
  }
  return undefined;
}
