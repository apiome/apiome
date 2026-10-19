/**
 * Layout of the bounded dependency-graph drawing — CDG-3.4 (#5969).
 *
 * Pure and unit-tested, like the sunset timeline's layout model: the component only draws what
 * this returns. The drawing is a picture of the list next to it, which stays the source of truth.
 *
 * The centred entity sits in the middle column. What points **at** it (incoming edges) sits in the
 * column to its left, what it points **to** (outgoing edges) in the column to its right. Expanding
 * a neighbour adds *its* neighbours one column further out on the same side, so the picture reaches
 * depth 2. Each column draws at most {@link MAX_NODES_PER_COLUMN} nodes and says how many more there
 * are — the layout never silently drops a node.
 */

import {
  EDGE_KIND_LABELS,
  NODE_KIND_ABBREVIATIONS,
  NODE_KIND_LABELS,
  graphNodeHref,
  nodeDisplayName,
  type EdgeNeighbour,
  type GraphEdgeKind,
  type GraphNodeKind,
  type GraphNodeLabel,
  type GraphProvenance,
} from '@lib/graph';

export const VIEW_WIDTH = 960;
export const COLUMN_GAP = 200;
export const ROW_HEIGHT = 56;
export const PLOT_TOP = 32;
export const NODE_RADIUS = 18;
export const MAX_NODES_PER_COLUMN = 10;
/** Longest node caption drawn before it is cut with an ellipsis. */
export const MAX_CAPTION = 22;

/** A column index: -2 … 2, the centre at 0. */
export type GraphColumn = -2 | -1 | 0 | 1 | 2;

export interface GraphLayoutNode {
  key: string;
  id: string;
  kind: GraphNodeKind;
  column: GraphColumn;
  x: number;
  y: number;
  name: string;
  caption: string;
  abbreviation: string;
  href: string;
  /** Every edge to it is stale (it is drawn dimmed). */
  stale: boolean;
  /** A depth-1 neighbour whose own neighbours can be drawn. */
  expandable: boolean;
  expanded: boolean;
  /** The accessible name: what it is and how it relates. */
  ariaLabel: string;
}

export interface GraphLayoutLink {
  key: string;
  from: string;
  to: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  edgeKind: GraphEdgeKind;
  provenance: GraphProvenance;
  stale: boolean;
}

export interface GraphLayoutOverflow {
  column: GraphColumn;
  x: number;
  y: number;
  hidden: number;
}

export interface GraphLayout {
  width: number;
  height: number;
  nodes: GraphLayoutNode[];
  links: GraphLayoutLink[];
  overflow: GraphLayoutOverflow[];
  /** How many neighbours exist but are not drawn, across all columns. */
  hiddenCount: number;
}

export interface GraphLayoutInput {
  centre: { kind: GraphNodeKind; id: string; label?: GraphNodeLabel | null };
  /** The centre's neighbours (both directions). */
  neighbours: readonly EdgeNeighbour[];
  /** For each expanded depth-1 node id, that node's neighbours. */
  expanded?: ReadonlyMap<string, readonly EdgeNeighbour[]>;
}

/** Cut a caption to {@link MAX_CAPTION} characters. */
export function caption(text: string): string {
  return text.length > MAX_CAPTION ? `${text.slice(0, MAX_CAPTION - 1)}…` : text;
}

function columnX(column: GraphColumn): number {
  return VIEW_WIDTH / 2 + column * COLUMN_GAP;
}

interface Placed {
  id: string;
  kind: GraphNodeKind;
  label: GraphNodeLabel | null;
  /** The node it hangs off (the centre for depth 1). */
  parent: string;
  edges: EdgeNeighbour[];
}

/**
 * Lay out the drawing.
 *
 * @param input - The centre, its neighbours, and the neighbours of each expanded node.
 * @returns Nodes, links and per-column overflow, in view-box units.
 */
export function graphLayout(input: GraphLayoutInput): GraphLayout {
  const centreId = input.centre.id;
  const columns = new Map<GraphColumn, Placed[]>();
  const placedIds = new Set<string>([centreId]);
  const totals = new Map<GraphColumn, number>();

  const place = (column: GraphColumn, neighbour: EdgeNeighbour, parent: string) => {
    const list = columns.get(column) ?? [];
    const existing = list.find((p) => p.id === neighbour.id && p.parent === parent);
    if (existing) {
      existing.edges.push(neighbour);
      return;
    }
    if (placedIds.has(neighbour.id)) return; // already drawn elsewhere: no duplicates
    totals.set(column, (totals.get(column) ?? 0) + 1);
    if (list.length >= MAX_NODES_PER_COLUMN) return;
    placedIds.add(neighbour.id);
    list.push({ id: neighbour.id, kind: neighbour.kind, label: neighbour.label, parent, edges: [neighbour] });
    columns.set(column, list);
  };

  for (const neighbour of input.neighbours) {
    if (neighbour.id === centreId) continue;
    place(neighbour.direction === 'in' ? -1 : 1, neighbour, centreId);
  }
  for (const column of [-1, 1] as const) {
    for (const node of [...(columns.get(column) ?? [])]) {
      const outer = (column * 2) as GraphColumn;
      for (const neighbour of input.expanded?.get(node.id) ?? []) {
        // Keep walking away from the centre: incoming on the left, outgoing on the right.
        if (neighbour.id === centreId || (column < 0 ? neighbour.direction !== 'in' : neighbour.direction !== 'out')) {
          continue;
        }
        place(outer, neighbour, node.id);
      }
    }
  }

  const rows = Math.max(1, ...[...columns.values()].map((list) => list.length + 1));
  const height = PLOT_TOP * 2 + rows * ROW_HEIGHT;
  const nodes: GraphLayoutNode[] = [];
  const positions = new Map<string, { x: number; y: number }>();
  const centreName = nodeDisplayName(input.centre.kind, centreId, input.centre.label);
  const centre: GraphLayoutNode = {
    key: `0:${centreId}`,
    id: centreId,
    kind: input.centre.kind,
    column: 0,
    x: columnX(0),
    y: height / 2,
    name: centreName,
    caption: caption(centreName),
    abbreviation: NODE_KIND_ABBREVIATIONS[input.centre.kind],
    href: graphNodeHref(input.centre.kind, centreId),
    stale: false,
    expandable: false,
    expanded: false,
    ariaLabel: `${NODE_KIND_LABELS[input.centre.kind]} ${centreName}, the entity shown`,
  };
  nodes.push(centre);
  positions.set(centreId, { x: centre.x, y: centre.y });

  const overflow: GraphLayoutOverflow[] = [];
  const links: GraphLayoutLink[] = [];
  const byId = new Map<string, Placed>();
  for (const column of [-1, 1] as const) for (const placed of columns.get(column) ?? []) byId.set(placed.id, placed);
  for (const column of [-1, 1, -2, 2] as const) {
    const list = columns.get(column) ?? [];
    const top = height / 2 - ((list.length - 1) * ROW_HEIGHT) / 2;
    list.forEach((placed, index) => {
      const name = nodeDisplayName(placed.kind, placed.id, placed.label);
      const parent = byId.get(placed.parent);
      const parentName = parent ? nodeDisplayName(parent.kind, parent.id, parent.label) : centreName;
      const verbs = placed.edges
        .map((e) => EDGE_KIND_LABELS[e.edge.edge_kind].out.toLowerCase())
        .filter((v, i, all) => all.indexOf(v) === i)
        .join(' and ');
      const allStale = placed.edges.every((e) => e.edge.stale);
      const sentence = column < 0 ? `${name} ${verbs} ${parentName}` : `${parentName} ${verbs} ${name}`;
      const node: GraphLayoutNode = {
        key: `${column}:${placed.id}`,
        id: placed.id,
        kind: placed.kind,
        column,
        x: columnX(column),
        y: top + index * ROW_HEIGHT,
        name,
        caption: caption(name),
        abbreviation: NODE_KIND_ABBREVIATIONS[placed.kind],
        href: graphNodeHref(placed.kind, placed.id),
        stale: allStale,
        expandable: Math.abs(column) === 1,
        expanded: Math.abs(column) === 1 && Boolean(input.expanded?.has(placed.id)),
        ariaLabel: `${NODE_KIND_LABELS[placed.kind]} ${name}: ${sentence}${allStale ? ' (stale)' : ''}`,
      };
      nodes.push(node);
      positions.set(placed.id, { x: node.x, y: node.y });
    });
    const hidden = (totals.get(column) ?? 0) - list.length;
    if (hidden > 0) {
      overflow.push({ column, x: columnX(column), y: top + list.length * ROW_HEIGHT, hidden });
    }
  }
  for (const column of [-1, 1, -2, 2] as const) {
    for (const placed of columns.get(column) ?? []) {
      const a = positions.get(placed.id);
      const b = positions.get(placed.parent);
      if (!a || !b) continue;
      for (const edge of placed.edges) {
        links.push({
          key: `${edge.edge.id}:${column}`,
          from: edge.direction === 'in' ? placed.id : placed.parent,
          to: edge.direction === 'in' ? placed.parent : placed.id,
          x1: column < 0 ? a.x : b.x,
          y1: column < 0 ? a.y : b.y,
          x2: column < 0 ? b.x : a.x,
          y2: column < 0 ? b.y : a.y,
          edgeKind: edge.edge.edge_kind,
          provenance: edge.edge.provenance,
          stale: edge.edge.stale,
        });
      }
    }
  }
  return {
    width: VIEW_WIDTH,
    height,
    nodes,
    links,
    overflow,
    hiddenCount: overflow.reduce((sum, o) => sum + o.hidden, 0),
  };
}

/** The drawing's accessible summary. */
export function graphAriaLabel(layout: GraphLayout): string {
  const centre = layout.nodes.find((n) => n.column === 0);
  const incoming = layout.nodes.filter((n) => n.column < 0).length;
  const outgoing = layout.nodes.filter((n) => n.column > 0).length;
  const more = layout.hiddenCount ? `, ${layout.hiddenCount} more not drawn` : '';
  return `Dependency graph of ${centre?.name ?? 'the entity'}: ${incoming} depend on it, it depends on ${outgoing}${more}`;
}
