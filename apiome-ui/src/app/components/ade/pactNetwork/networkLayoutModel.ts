/**
 * Layout of the integration network drawing — PFX-5.3 (#6947).
 *
 * Pure and unit-tested, like the dependency graph's layout model: the SVG only draws what this
 * returns, and the integrations table beside it stays the source of truth.
 *
 * The drawing is layered from consumers to providers, left to right: each provider sits one column
 * right of its furthest consumer, and a pacticipant that only consumes sits one column left of its
 * nearest provider. A cycle (two pacticipants that consume each other, or a longer loop) is broken
 * where the walk first closes it; that edge is drawn as an arc under the nodes instead. Each column
 * draws at most {@link MAX_NODES_PER_LAYER} pacticipants and says how many more there are; an edge
 * to a pacticipant that is not drawn is left out of the picture but not out of the table.
 */

import {
  networkRoute,
  type NetworkGap,
  type NetworkIntegration,
  type PactNetwork,
  verdictCounts,
} from '@lib/pact-network';
import { VERDICT_LABELS, pactRoute, type VerificationVerdict } from '@lib/pact-detail';
import { shortVersion } from '@lib/pact-pacticipants';

export const NODE_WIDTH = 176;
export const NODE_HEIGHT = 40;
export const COLUMN_GAP = 264;
export const ROW_HEIGHT = 72;
export const PAD_X = 24;
export const PAD_Y = 32;
/** How far below the nodes a backward edge's arc reaches. */
export const LOOP_DEPTH = 44;
/** The gap left before a node for the arrowhead. */
export const ARROW_GAP = 6;
export const MIN_WIDTH = 640;
export const MAX_NODES_PER_LAYER = 12;
/** Longest caption drawn inside a node before it is cut with an ellipsis. */
export const MAX_CAPTION = 22;

/** Every verdict, in the order the key and the summary name them. */
export const VERDICT_ORDER: VerificationVerdict[] = [
  'verified',
  'failed',
  'failed-pending',
  'unverified',
];

/** The mark drawn on each edge, so the verdict never rests on colour alone. */
export const VERDICT_GLYPHS: Record<VerificationVerdict, string> = {
  verified: '✓',
  failed: '✕',
  'failed-pending': '!',
  unverified: '?',
};

export interface NetworkLayoutNode {
  slug: string;
  name: string;
  caption: string;
  layer: number;
  x: number;
  y: number;
  centre: boolean;
  gap: NetworkGap | null;
  href: string;
  ariaLabel: string;
}

export interface NetworkLayoutEdge {
  key: string;
  consumer: string;
  provider: string;
  verdict: VerificationVerdict;
  /** The SVG path (`M … C …`). */
  d: string;
  /** Where the verdict mark sits (the curve's midpoint). */
  markX: number;
  markY: number;
  /** Drawn as an arc under the nodes (it closes a cycle or stays in one column). */
  backward: boolean;
  href: string;
  ariaLabel: string;
}

export interface NetworkLayoutOverflow {
  layer: number;
  x: number;
  y: number;
  hidden: number;
}

export interface NetworkLayout {
  width: number;
  height: number;
  nodes: NetworkLayoutNode[];
  edges: NetworkLayoutEdge[];
  overflow: NetworkLayoutOverflow[];
  /** Pacticipants in the network that are not drawn. */
  hiddenNodes: number;
  /** Integrations not drawn (an end is not drawn, or it is a pacticipant's pact with itself). */
  hiddenEdges: number;
}

/** Cut a caption to {@link MAX_CAPTION} characters. */
export function caption(text: string): string {
  return text.length > MAX_CAPTION ? `${text.slice(0, MAX_CAPTION - 1)}…` : text;
}

/**
 * Each pacticipant's column: the longest consumer chain that leads to it, once the edges that close
 * a cycle are set aside.
 *
 * @param order - Every handle, in the order the walk visits them (the centre first).
 * @param integrations - The edges, consumer → provider.
 * @returns The column of each handle, and the keys (`consumer|provider`) of the edges set aside.
 */
export function assignLayers(
  order: readonly string[],
  integrations: readonly NetworkIntegration[],
): { layers: Map<string, number>; backEdges: Set<string> } {
  const out = new Map<string, string[]>();
  for (const slug of order) out.set(slug, []);
  for (const i of integrations) {
    if (i.consumer.slug !== i.provider.slug) out.get(i.consumer.slug)?.push(i.provider.slug);
  }
  // Depth-first: an edge to a node still on the stack closes a cycle.
  const state = new Map<string, 'open' | 'done'>();
  const backEdges = new Set<string>();
  const visit = (slug: string) => {
    state.set(slug, 'open');
    for (const next of out.get(slug) ?? []) {
      const seen = state.get(next);
      if (seen === 'open') backEdges.add(`${slug}|${next}`);
      else if (!seen) visit(next);
    }
    state.set(slug, 'done');
  };
  for (const slug of order) if (!state.has(slug)) visit(slug);

  const incoming = new Map<string, string[]>();
  for (const slug of order) incoming.set(slug, []);
  for (const [from, targets] of out) {
    for (const to of targets) if (!backEdges.has(`${from}|${to}`)) incoming.get(to)?.push(from);
  }
  const layers = new Map<string, number>();
  const layerOf = (slug: string): number => {
    const known = layers.get(slug);
    if (known !== undefined) return known;
    layers.set(slug, 0); // the forward edges form no cycle; this only guards a bad input
    const layer = Math.max(-1, ...(incoming.get(slug) ?? []).map(layerOf)) + 1;
    layers.set(slug, layer);
    return layer;
  };
  for (const slug of order) layerOf(slug);
  // A pure consumer moves right, next to its nearest provider, so its arrows do not run behind the
  // columns in between.
  for (const slug of order) {
    if ((incoming.get(slug) ?? []).length > 0) continue;
    const targets = (out.get(slug) ?? []).filter((to) => !backEdges.has(`${slug}|${to}`));
    if (targets.length === 0) continue;
    layers.set(slug, Math.max(0, Math.min(...targets.map((to) => layers.get(to) ?? 0)) - 1));
  }
  return { layers, backEdges };
}

/** A point on a cubic Bézier curve at t = ½. */
function midpoint(p: number[]): [number, number] {
  const [x0, y0, x1, y1, x2, y2, x3, y3] = p;
  return [(x0 + 3 * x1 + 3 * x2 + x3) / 8, (y0 + 3 * y1 + 3 * y2 + y3) / 8];
}

/**
 * Lay out the drawing.
 *
 * @param network - The network, as the proxy answers it.
 * @returns Nodes, edges and per-column overflow, in view-box units.
 */
export function networkLayout(network: PactNetwork): NetworkLayout {
  const order = network.pacticipants.map((p) => p.slug);
  const { layers, backEdges } = assignLayers(order, network.integrations);
  const layerCount = Math.max(0, ...layers.values()) + 1;

  // Column order: the proxy's order (nearest first, by name), then one pass that pulls each
  // pacticipant level with its consumers, so fewer edges cross.
  const columns: string[][] = Array.from({ length: layerCount }, () => []);
  for (const slug of order) columns[layers.get(slug) ?? 0].push(slug);
  const rowOf = new Map<string, number>();
  columns[0]?.forEach((slug, index) => rowOf.set(slug, index));
  for (let layer = 1; layer < layerCount; layer += 1) {
    const score = (slug: string, fallback: number) => {
      const rows = network.integrations
        .filter((i) => i.provider.slug === slug && rowOf.has(i.consumer.slug))
        .map((i) => rowOf.get(i.consumer.slug)!);
      return rows.length > 0 ? rows.reduce((a, b) => a + b, 0) / rows.length : fallback;
    };
    const scored = columns[layer].map((slug, index) => ({
      slug,
      index,
      score: score(slug, index),
    }));
    scored.sort((a, b) => a.score - b.score || a.index - b.index);
    columns[layer] = scored.map((s) => s.slug);
    columns[layer].forEach((slug, index) => rowOf.set(slug, index));
  }

  // The centre is always drawn, even in a crowded column.
  const drawn = columns.map((column) => {
    const shown = column.slice(0, MAX_NODES_PER_LAYER);
    if (column.includes(network.centre) && !shown.includes(network.centre)) {
      shown[shown.length - 1] = network.centre;
    }
    return shown;
  });

  const rows = Math.max(
    1,
    ...drawn.map((column, i) => column.length + (columns[i].length > column.length ? 1 : 0)),
  );
  const plotHeight = rows * ROW_HEIGHT;
  const arcs = network.integrations.some(
    (i) =>
      backEdges.has(`${i.consumer.slug}|${i.provider.slug}`) ||
      (layers.get(i.provider.slug) ?? 0) <= (layers.get(i.consumer.slug) ?? 0),
  );
  const height = PAD_Y * 2 + plotHeight + (arcs ? LOOP_DEPTH : 0);
  const width = Math.max(MIN_WIDTH, PAD_X * 2 + (layerCount - 1) * COLUMN_GAP + NODE_WIDTH);
  const left = (width - ((layerCount - 1) * COLUMN_GAP + NODE_WIDTH)) / 2;
  const centreY = PAD_Y + plotHeight / 2;

  const bySlug = new Map(network.pacticipants.map((p) => [p.slug, p]));
  const nodes: NetworkLayoutNode[] = [];
  const overflow: NetworkLayoutOverflow[] = [];
  const positions = new Map<string, NetworkLayoutNode>();
  drawn.forEach((column, layer) => {
    const x = left + layer * COLUMN_GAP + NODE_WIDTH / 2;
    const top = centreY - ((column.length - 1) * ROW_HEIGHT) / 2;
    column.forEach((slug, index) => {
      const p = bySlug.get(slug)!;
      const consumes = network.integrations.filter((i) => i.consumer.slug === slug).length;
      const provides = network.integrations.filter((i) => i.provider.slug === slug).length;
      const centre = slug === network.centre;
      const node: NetworkLayoutNode = {
        slug,
        name: p.name,
        caption: caption(p.name),
        layer,
        x,
        y: top + index * ROW_HEIGHT,
        centre,
        gap: p.gap ?? null,
        href: networkRoute(slug),
        ariaLabel:
          `${p.name}${centre ? ', the pacticipant shown' : ''}: consumes ${consumes}, provides to ${provides}` +
          `${p.gap === 'failed' ? ' (its pacts could not be read)' : p.gap === 'not-read' ? ' (its pacts were not read)' : ''}. Open its network.`,
      };
      nodes.push(node);
      positions.set(slug, node);
    });
    const hidden = columns[layer].length - column.length;
    if (hidden > 0) overflow.push({ layer, x, y: top + column.length * ROW_HEIGHT, hidden });
  });

  const edges: NetworkLayoutEdge[] = [];
  for (const integration of network.integrations) {
    const a = positions.get(integration.consumer.slug);
    const b = positions.get(integration.provider.slug);
    if (!a || !b || a === b) continue;
    const key = `${integration.consumer.slug}|${integration.provider.slug}`;
    const backward = backEdges.has(key) || b.layer <= a.layer;
    let points: number[];
    if (backward) {
      const sy = a.y + NODE_HEIGHT / 2;
      const ey = b.y + NODE_HEIGHT / 2 + ARROW_GAP;
      const depth = Math.max(sy, ey) + LOOP_DEPTH;
      points = [a.x, sy, a.x, depth, b.x, depth, b.x, ey];
    } else {
      const sx = a.x + NODE_WIDTH / 2;
      const ex = b.x - NODE_WIDTH / 2 - ARROW_GAP;
      const bend = (ex - sx) / 2;
      points = [sx, a.y, sx + bend, a.y, ex - bend, b.y, ex, b.y];
    }
    const [markX, markY] = midpoint(points);
    const [x0, y0, x1, y1, x2, y2, x3, y3] = points;
    edges.push({
      key,
      consumer: integration.consumer.slug,
      provider: integration.provider.slug,
      verdict: integration.verdict,
      d: `M ${x0} ${y0} C ${x1} ${y1}, ${x2} ${y2}, ${x3} ${y3}`,
      markX,
      markY,
      backward,
      href: pactRoute(integration.consumer.slug, integration.provider.slug),
      ariaLabel: `${integration.consumer.name} → ${integration.provider.name}: ${VERDICT_LABELS[integration.verdict]}, consumer version ${shortVersion(integration.latestVersion)}. Open the pact.`,
    });
  }

  return {
    width,
    height,
    nodes,
    edges,
    overflow,
    hiddenNodes: network.pacticipants.length - nodes.length,
    hiddenEdges: network.integrations.length - edges.length,
  };
}

/**
 * The drawing's accessible summary.
 *
 * @param network - The network.
 * @param layout - Its layout.
 * @returns E.g. `Network of Billing Service: 4 pacticipants, 4 integrations (2 Verified, 1 Failed, 1 Not verified yet)`.
 */
export function networkAriaLabel(network: PactNetwork, layout: NetworkLayout): string {
  const centre = network.pacticipants.find((p) => p.slug === network.centre);
  const counts = verdictCounts(network.integrations);
  const verdicts = VERDICT_ORDER.filter((verdict) => counts[verdict] > 0)
    .map((verdict) => `${counts[verdict]} ${VERDICT_LABELS[verdict]}`)
    .join(', ');
  const hidden =
    layout.hiddenNodes || layout.hiddenEdges
      ? `; ${layout.hiddenNodes} pacticipants and ${layout.hiddenEdges} integrations are only in the table`
      : '';
  const n = network.integrations.length;
  return `Network of ${centre?.name ?? network.centre}: ${network.pacticipants.length} pacticipants, ${n} ${n === 1 ? 'integration' : 'integrations'}${verdicts ? ` (${verdicts})` : ''}${hidden}`;
}
