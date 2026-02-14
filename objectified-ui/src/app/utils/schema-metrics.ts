/**
 * Schema metrics computed from canvas nodes and edges.
 * Used for the Schema Metrics view (#472).
 */

import type { Node, Edge } from '@xyflow/react';

export interface SchemaMetricsResult {
  /** Total number of class nodes (excludes group nodes) */
  classCount: number;
  /** Total number of properties across all classes */
  totalProperties: number;
  /** Average properties per class (0 if no classes) */
  averagePropertiesPerClass: number;
  /** Number of relationship edges */
  relationshipCount: number;
  /** Class ids with most connections (hubs), sorted by degree descending */
  hubClassIds: string[];
  /** Hub names for display (id -> name from nodes) */
  hubNames: string[];
  /** Class ids with zero relationships (isolated) */
  isolatedClassIds: string[];
  /** Isolated class names for display */
  isolatedNames: string[];
  /** Length of the deepest dependency chain (longest path in graph) */
  deepestChainLength: number;
  /** Number of distinct circular dependency groups (strongly connected components with size > 1) */
  circularDependencyCount: number;
  /** Optional: class names involved in cycles (sample) for tooltip */
  circularSampleNames: string[];
  /** Realtime schema complexity score 0–100 (#556) */
  complexityScore: number;
  /** Human-readable complexity band for display */
  complexityLabel: 'Low' | 'Medium' | 'High';
  /** Per-factor contribution for "why is this score" breakdown */
  complexityBreakdown: ComplexityBreakdownItem[];
}

export interface ComplexityBreakdownItem {
  label: string;
  value: number;
  weight: number;
  contribution: number;
}

function getClassNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) => n.type !== 'groupNode');
}

function getPropertyCount(node: Node): number {
  const props = (node.data as { properties?: unknown[] })?.properties;
  return Array.isArray(props) ? props.length : 0;
}

/**
 * Build directed adjacency list: nodeId -> [targetIds]
 */
function buildDirectedAdjacency(edges: Edge[]): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    const src = e.source;
    const tgt = e.target;
    if (!adj.has(src)) adj.set(src, []);
    adj.get(src)!.push(tgt);
  }
  return adj;
}

/**
 * Degree (in + out) per node
 */
function getDegreePerNode(nodes: Node[], edges: Edge[]): Map<string, number> {
  const degree = new Map<string, void>();
  for (const n of nodes) degree.set(n.id, undefined);
  for (const e of edges) {
    degree.set(e.source, undefined);
    degree.set(e.target, undefined);
  }
  const count = new Map<string, number>();
  for (const id of degree.keys()) count.set(id, 0);
  for (const e of edges) {
    count.set(e.source, (count.get(e.source) ?? 0) + 1);
    count.set(e.target, (count.get(e.target) ?? 0) + 1);
  }
  return count;
}

/**
 * Longest path from a node (DFS, visited set per path to avoid infinite loop in cycles).
 * Returns max depth (number of edges), so chain "length" in terms of steps.
 */
function longestPathFrom(
  nodeId: string,
  adj: Map<string, string[]>,
  visitedInPath: Set<string>
): number {
  if (visitedInPath.has(nodeId)) return 0;
  const next = adj.get(nodeId);
  if (!next || next.length === 0) return 0;
  visitedInPath.add(nodeId);
  let max = 0;
  for (const t of next) {
    const d = 1 + longestPathFrom(t, adj, visitedInPath);
    if (d > max) max = d;
  }
  visitedInPath.delete(nodeId);
  return max;
}

/**
 * Deepest dependency chain = max over all nodes of (longest path from that node).
 */
function computeDeepestChain(adj: Map<string, string[]>, nodeIds: Set<string>): number {
  let maxChain = 0;
  for (const id of nodeIds) {
    const depth = longestPathFrom(id, adj, new Set());
    if (depth > maxChain) maxChain = depth;
  }
  return maxChain;
}

/**
 * Find strongly connected components (Tarjan) to count cycles.
 * Returns number of SCCs with more than one node (or one node with a self-loop).
 */
function countCircularDependencies(adj: Map<string, string[]>, nodeIds: Set<string>): {
  count: number;
  sampleNodeIds: string[];
} {
  const index = new Map<string, number>();
  const lowLink = new Map<string, number>();
  const onStack = new Map<string, boolean>();
  const stack: string[] = [];
  let currentIndex = 0;
  const sccs: string[][] = [];

  function strongconnect(v: string): void {
    index.set(v, currentIndex);
    lowLink.set(v, currentIndex);
    currentIndex++;
    stack.push(v);
    onStack.set(v, true);

    for (const w of adj.get(v) ?? []) {
      if (!nodeIds.has(w)) continue;
      if (!index.has(w)) {
        strongconnect(w);
        lowLink.set(v, Math.min(lowLink.get(v)!, lowLink.get(w)!));
      } else if (onStack.get(w)) {
        lowLink.set(v, Math.min(lowLink.get(v)!, index.get(w)!));
      }
    }

    if (lowLink.get(v) === index.get(v)) {
      const scc: string[] = [];
      let w: string;
      do {
        w = stack.pop()!;
        onStack.set(w, false);
        scc.push(w);
      } while (w !== v);
      sccs.push(scc);
    }
  }

  for (const id of nodeIds) {
    if (!index.has(id)) strongconnect(id);
  }

  const circularSccs = sccs.filter((scc) => scc.length > 1 || (scc.length === 1 && (adj.get(scc[0])?.includes(scc[0]) ?? false)));
  const sampleNodeIds = circularSccs.flat().slice(0, 10);
  return { count: circularSccs.length, sampleNodeIds };
}

function getNodeName(node: Node): string {
  const name = (node.data as { name?: string })?.name;
  return typeof name === 'string' ? name : node.id;
}

/**
 * Compute all schema metrics from current canvas nodes and edges.
 */
export function computeSchemaMetrics(nodes: Node[], edges: Edge[]): SchemaMetricsResult {
  const classNodes = getClassNodes(nodes);
  const nodeIds = new Set(classNodes.map((n) => n.id));
  const idToNode = new Map(classNodes.map((n) => [n.id, n]));

  const totalProperties = classNodes.reduce((sum, n) => sum + getPropertyCount(n), 0);
  const classCount = classNodes.length;
  const averagePropertiesPerClass =
    classCount === 0 ? 0 : Math.round((totalProperties / classCount) * 10) / 10;

  const degreeMap = getDegreePerNode(classNodes, edges);
  const sortedByDegree = [...classNodes].sort(
    (a, b) => (degreeMap.get(b.id) ?? 0) - (degreeMap.get(a.id) ?? 0)
  );
  const hubClassIds = sortedByDegree.filter((n) => (degreeMap.get(n.id) ?? 0) > 0).map((n) => n.id);
  const hubNames = hubClassIds.map((id) => getNodeName(idToNode.get(id)!)).filter(Boolean);

  const isolatedClassIds = classNodes.filter((n) => (degreeMap.get(n.id) ?? 0) === 0).map((n) => n.id);
  const isolatedNames = isolatedClassIds.map((id) => getNodeName(idToNode.get(id)!)).filter(Boolean);

  const adj = buildDirectedAdjacency(edges);
  const deepestChainLength = computeDeepestChain(adj, nodeIds);
  const { count: circularDependencyCount, sampleNodeIds } = countCircularDependencies(adj, nodeIds);
  const circularSampleNames = sampleNodeIds
    .map((id) => idToNode.get(id))
    .filter(Boolean)
    .map((n) => getNodeName(n!));

  const { complexityScore, complexityLabel, complexityBreakdown } = computeComplexityScore({
    classCount,
    totalProperties,
    averagePropertiesPerClass,
    relationshipCount: edges.length,
    deepestChainLength,
    circularDependencyCount,
  });

  return {
    classCount,
    totalProperties,
    averagePropertiesPerClass,
    relationshipCount: edges.length,
    hubClassIds,
    hubNames,
    isolatedClassIds,
    isolatedNames,
    deepestChainLength,
    circularDependencyCount,
    circularSampleNames,
    complexityScore,
    complexityLabel,
    complexityBreakdown,
  };
}

/**
 * Compute a 0–100 schema complexity score, label, and per-factor breakdown (#556).
 * Based on class count, property count, relationships, depth, and cycles.
 */
function computeComplexityScore(metrics: {
  classCount: number;
  totalProperties: number;
  averagePropertiesPerClass: number;
  relationshipCount: number;
  deepestChainLength: number;
  circularDependencyCount: number;
}): {
  complexityScore: number;
  complexityLabel: 'Low' | 'Medium' | 'High';
  complexityBreakdown: ComplexityBreakdownItem[];
} {
  const weights = {
    classCount: 1.5,
    totalProperties: 0.3,
    relationshipCount: 1.2,
    averagePropertiesPerClass: 1.5,
    deepestChainLength: 4,
    circularDependencyCount: 6,
  };
  const breakdown: ComplexityBreakdownItem[] = [
    { label: 'Classes', value: metrics.classCount, weight: weights.classCount, contribution: metrics.classCount * weights.classCount },
    { label: 'Total properties', value: metrics.totalProperties, weight: weights.totalProperties, contribution: metrics.totalProperties * weights.totalProperties },
    { label: 'Relationships', value: metrics.relationshipCount, weight: weights.relationshipCount, contribution: metrics.relationshipCount * weights.relationshipCount },
    { label: 'Avg properties/class', value: metrics.averagePropertiesPerClass, weight: weights.averagePropertiesPerClass, contribution: metrics.averagePropertiesPerClass * weights.averagePropertiesPerClass },
    { label: 'Deepest chain (steps)', value: metrics.deepestChainLength, weight: weights.deepestChainLength, contribution: metrics.deepestChainLength * weights.deepestChainLength },
    { label: 'Circular dependencies', value: metrics.circularDependencyCount, weight: weights.circularDependencyCount, contribution: metrics.circularDependencyCount * weights.circularDependencyCount },
  ];
  const raw = breakdown.reduce((sum, b) => sum + b.contribution, 0);
  const complexityScore = Math.min(100, Math.max(0, Math.round(raw)));
  const complexityLabel: 'Low' | 'Medium' | 'High' =
    complexityScore <= 33 ? 'Low' : complexityScore <= 66 ? 'Medium' : 'High';
  return { complexityScore, complexityLabel, complexityBreakdown: breakdown };
}
