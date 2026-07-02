/**
 * Layout quality metrics for the canvas (#473).
 * Computed from node positions and edges.
 */

import type { Node, Edge } from '@xyflow/react';

export interface LayoutQualityResult {
  /** Number of edge crossings (lower is better) */
  edgeCrossingCount: number;
  /** 0–100: higher = more uniform spacing between nodes */
  nodeSpacingUniformityScore: number;
  /** 0–100: higher = more symmetric layout around center */
  layoutSymmetryScore: number;
  /** 0–100: higher = better visual balance (mass near center) */
  visualBalanceScore: number;
  /** 0–100: overall layout quality (average of the three scores, crossing count factored in) */
  overallScore: number;
}

const DEFAULT_NODE_WIDTH = 200;
const DEFAULT_NODE_HEIGHT = 150;

function getNodeCenter(node: Node): { x: number; y: number } {
  const p = node.position;
  const x = typeof p.x === 'number' ? p.x : 0;
  const y = typeof p.y === 'number' ? p.y : 0;
  const w = (node as any).measured?.width ?? (node as any).width ?? DEFAULT_NODE_WIDTH;
  const h = (node as any).measured?.height ?? (node as any).height ?? DEFAULT_NODE_HEIGHT;
  return { x: x + Number(w) / 2, y: y + Number(h) / 2 };
}

/**
 * Check if two line segments (a1->a2 and b1->b2) intersect (excluding endpoints).
 * Uses orientation-based intersection test.
 */
function segmentsIntersect(
  a1: { x: number; y: number },
  a2: { x: number; y: number },
  b1: { x: number; y: number },
  b2: { x: number; y: number }
): boolean {
  const cross = (o: { x: number; y: number }, p: { x: number; y: number }, q: { x: number; y: number }) =>
    (p.x - o.x) * (q.y - o.y) - (p.y - o.y) * (q.x - o.x);

  const d1 = cross(a1, a2, b1);
  const d2 = cross(a1, a2, b2);
  const d3 = cross(b1, b2, a1);
  const d4 = cross(b1, b2, a2);

  if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) return true;
  if (d1 === 0 && d2 === 0 && d3 === 0 && d4 === 0) {
    // Collinear: check if segments overlap (project to x or y)
    const overlap = (a: number, b: number, c: number, d: number) =>
      Math.max(a, b) >= Math.min(c, d) && Math.max(c, d) >= Math.min(a, b);
    return overlap(a1.x, a2.x, b1.x, b2.x) && overlap(a1.y, a2.y, b1.y, b2.y);
  }
  return false;
}

function getClassNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) => n.type !== 'groupNode');
}

/**
 * Count pairs of edges that cross (using node centers). Edges that share a node are not counted.
 */
function countEdgeCrossings(nodes: Node[], edges: Edge[], idToNode: Map<string, Node>): number {
  let count = 0;
  const segments: { a: { x: number; y: number }; b: { x: number; y: number }; source: string; target: string }[] = [];

  for (const e of edges) {
    const src = idToNode.get(e.source);
    const tgt = idToNode.get(e.target);
    if (!src || !tgt) continue;
    const a = getNodeCenter(src);
    const b = getNodeCenter(tgt);
    segments.push({ a, b, source: e.source, target: e.target });
  }

  for (let i = 0; i < segments.length; i++) {
    for (let j = i + 1; j < segments.length; j++) {
      const s1 = segments[i];
      const s2 = segments[j];
      const shareNode =
        s1.source === s2.source ||
        s1.source === s2.target ||
        s1.target === s2.source ||
        s1.target === s2.target;
      if (shareNode) continue;
      if (segmentsIntersect(s1.a, s1.b, s2.a, s2.b)) count++;
    }
  }
  return count;
}

/**
 * Nearest-neighbor distance for each node; return mean and std dev.
 */
function nearestNeighborStats(nodes: Node[], idToCenter: Map<string, { x: number; y: number }>): { mean: number; stdDev: number } {
  const ids = nodes.map((n) => n.id);
  const distances: number[] = [];

  for (const node of nodes) {
    const c = idToCenter.get(node.id);
    if (!c) continue;
    let minDist = Infinity;
    for (const otherId of ids) {
      if (otherId === node.id) continue;
      const o = idToCenter.get(otherId);
      if (!o) continue;
      const d = Math.hypot(c.x - o.x, c.y - o.y);
      if (d < minDist) minDist = d;
    }
    if (minDist !== Infinity) distances.push(minDist);
  }

  if (distances.length === 0) return { mean: 0, stdDev: 0 };
  const mean = distances.reduce((a, b) => a + b, 0) / distances.length;
  const variance = distances.reduce((s, d) => s + (d - mean) ** 2, 0) / distances.length;
  const stdDev = Math.sqrt(variance);
  return { mean, stdDev };
}

/**
 * 0–100 score: higher = more uniform. Uses coefficient of variation (stdDev/mean); lower CV = more uniform.
 */
function spacingUniformityScore(mean: number, stdDev: number): number {
  if (mean <= 0) return 100;
  const cv = stdDev / mean;
  // Map CV to score: CV 0 -> 100, CV >= 1 -> ~0
  const score = Math.max(0, 100 - cv * 80);
  return Math.round(score);
}

/**
 * Symmetry: reflect nodes around center of mass; measure how close each node is to a reflected counterpart.
 * Score 0–100: higher = more symmetric.
 */
function layoutSymmetryScore(nodes: Node[], centers: Map<string, { x: number; y: number }>): number {
  if (nodes.length < 2) return 100;
  const pts = nodes.map((n) => ({ id: n.id, ...centers.get(n.id)! })).filter((p) => p.x !== undefined);
  if (pts.length < 2) return 100;

  const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;

  // Reflect each point around center and find min distance to any other point (symmetric counterpart)
  let totalRatio = 0;
  for (const p of pts) {
    const rx = 2 * cx - p.x;
    const ry = 2 * cy - p.y;
    let minDist = Infinity;
    for (const q of pts) {
      if (q.id === p.id) continue;
      const d = Math.hypot(rx - q.x, ry - q.y);
      if (d < minDist) minDist = d;
    }
    const distFromCenter = Math.hypot(p.x - cx, p.y - cy);
    const ratio = distFromCenter > 1 ? minDist / distFromCenter : 1;
    totalRatio += ratio;
  }
  const avgRatio = totalRatio / pts.length;
  // Low ratio = reflected point is close to someone = symmetric. Map to 0–100.
  const score = Math.min(100, Math.max(0, 100 - avgRatio * 50));
  return Math.round(score);
}

/**
 * Visual balance: center of mass vs bounding box center. Closer = more balanced. 0–100.
 */
function visualBalanceScore(nodes: Node[], centers: Map<string, { x: number; y: number }>): number {
  if (nodes.length === 0) return 100;
  const pts = nodes.map((n) => centers.get(n.id)).filter(Boolean) as { x: number; y: number }[];
  if (pts.length === 0) return 100;

  const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
  const minX = Math.min(...pts.map((p) => p.x));
  const maxX = Math.max(...pts.map((p) => p.x));
  const minY = Math.min(...pts.map((p) => p.y));
  const maxY = Math.max(...pts.map((p) => p.y));
  const boxCx = (minX + maxX) / 2;
  const boxCy = (minY + maxY) / 2;
  const span = Math.max(maxX - minX, maxY - minY, 1);
  const offset = Math.hypot(cx - boxCx, cy - boxCy);
  const normalizedOffset = offset / span;
  const score = Math.max(0, 100 - normalizedOffset * 100);
  return Math.round(score);
}

/**
 * Compute layout quality from current nodes and edges.
 * Only class nodes (non-group) are considered; positions must be present.
 */
export function computeLayoutQuality(nodes: Node[], edges: Edge[]): LayoutQualityResult | null {
  const classNodes = getClassNodes(nodes);
  if (classNodes.length === 0) return null;

  const idToNode = new Map(classNodes.map((n) => [n.id, n]));
  const idToCenter = new Map(classNodes.map((n) => [n.id, getNodeCenter(n)]));

  const edgeCrossingCount = countEdgeCrossings(classNodes, edges, idToNode);

  const { mean: spacingMean, stdDev: spacingStdDev } = nearestNeighborStats(classNodes, idToCenter);
  const nodeSpacingUniformityScore = spacingUniformityScore(spacingMean, spacingStdDev);

  const layoutSymmetryScoreVal = layoutSymmetryScore(classNodes, idToCenter);
  const visualBalanceScoreVal = visualBalanceScore(classNodes, idToCenter);

  // Penalize crossings: each crossing reduces overall score
  const crossingPenalty = Math.min(30, edgeCrossingCount * 3);
  const avgScore =
    (nodeSpacingUniformityScore + layoutSymmetryScoreVal + visualBalanceScoreVal) / 3;
  const overallScore = Math.round(Math.max(0, Math.min(100, avgScore - crossingPenalty)));

  return {
    edgeCrossingCount,
    nodeSpacingUniformityScore,
    layoutSymmetryScore: layoutSymmetryScoreVal,
    visualBalanceScore: visualBalanceScoreVal,
    overallScore,
  };
}
