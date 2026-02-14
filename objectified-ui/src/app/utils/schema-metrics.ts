/**
 * Schema metrics computed from canvas nodes and edges.
 * Used for the Schema Metrics view (#472).
 */

import type { Node, Edge } from '@xyflow/react';
import { detectNamingConvention } from './naming-conventions';

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
  /** Documentation completion 0–100: % of classes and properties with non-empty description (#557) */
  documentationCompletionPercentage: number;
  /** Class names that have no description (for "click to see where coverage is missing") */
  classesMissingDocumentation: string[];
  /** Properties missing description: className + propertyName for display */
  propertiesMissingDocumentation: { className: string; propertyName: string }[];
  /** Naming convention compliance (#558): camelCase, snake_case, PascalCase breakdown */
  namingCompliance: NamingComplianceResult;
}

/** Naming convention counts and compliance percentage (#558) */
export interface NamingComplianceResult {
  /** Class names: count per convention (recommended: PascalCase) */
  classes: { pascal: number; camel: number; snake: number; other: number; total: number };
  /** Property names: count per convention (recommended: camelCase) */
  properties: { pascal: number; camel: number; snake: number; other: number; total: number };
  /** Compliance 0–100: classes PascalCase + properties camelCase over total names */
  compliancePercentage: number;
  /** Class names that are not PascalCase (for "click to see" list) */
  classesNonPascal: string[];
  /** Properties not camelCase: className + propertyName (for "click to see" list) */
  propertiesNonCamel: { className: string; propertyName: string }[];
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

function hasDocumentation(value: unknown): boolean {
  if (value == null) return false;
  const s = typeof value === 'string' ? value : String(value);
  return s.trim().length > 0;
}

type DocGapResult = {
  percentage: number;
  classesMissing: string[];
  propertiesMissing: { className: string; propertyName: string }[];
};

/**
 * Compute documentation completion and list classes/properties missing description (#557).
 */
function computeDocumentationCompletion(classNodes: Node[]): DocGapResult {
  let documented = 0;
  let total = 0;
  const classesMissing: string[] = [];
  const propertiesMissing: { className: string; propertyName: string }[] = [];

  for (const node of classNodes) {
    const data = node.data as {
      name?: string;
      description?: string;
      properties?: Array<{ name?: string; description?: string }>;
    };
    const className = typeof data?.name === 'string' ? data.name : node.id;
    total += 1;
    if (hasDocumentation(data?.description)) {
      documented += 1;
    } else {
      classesMissing.push(className);
    }
    const props = data?.properties;
    if (Array.isArray(props)) {
      for (const p of props) {
        total += 1;
        const propName = typeof p?.name === 'string' ? p.name : 'property';
        if (hasDocumentation(p?.description)) {
          documented += 1;
        } else {
          propertiesMissing.push({ className, propertyName: propName });
        }
      }
    }
  }

  const percentage = total === 0 ? 100 : Math.round((documented / total) * 100);
  return { percentage, classesMissing, propertiesMissing };
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
 * Compute naming convention compliance for classes (PascalCase) and properties (camelCase) (#558).
 */
function computeNamingCompliance(classNodes: Node[]): NamingComplianceResult {
  const classes = { pascal: 0, camel: 0, snake: 0, other: 0, total: 0 };
  const properties = { pascal: 0, camel: 0, snake: 0, other: 0, total: 0 };
  const classesNonPascal: string[] = [];
  const propertiesNonCamel: { className: string; propertyName: string }[] = [];

  for (const node of classNodes) {
    const data = node.data as {
      name?: string;
      properties?: Array<{ name?: string }>;
    };
    const className = typeof data?.name === 'string' ? data.name : node.id;

    const classConv = detectNamingConvention(className);
    classes.total += 1;
    if (classConv === 'PascalCase') classes.pascal += 1;
    else if (classConv === 'camelCase') classes.camel += 1;
    else if (classConv === 'snake_case') classes.snake += 1;
    else classes.other += 1;
    if (classConv !== 'PascalCase') classesNonPascal.push(className);

    const props = data?.properties;
    if (Array.isArray(props)) {
      for (const p of props) {
        const propName = typeof p?.name === 'string' ? p.name : 'property';
        const propConv = detectNamingConvention(propName);
        properties.total += 1;
        if (propConv === 'PascalCase') properties.pascal += 1;
        else if (propConv === 'camelCase') properties.camel += 1;
        else if (propConv === 'snake_case') properties.snake += 1;
        else properties.other += 1;
        if (propConv !== 'camelCase') propertiesNonCamel.push({ className, propertyName: propName });
      }
    }
  }

  const compliant = classes.pascal + properties.camel;
  const totalNames = classes.total + properties.total;
  const compliancePercentage = totalNames === 0 ? 100 : Math.round((compliant / totalNames) * 100);

  return {
    classes,
    properties,
    compliancePercentage,
    classesNonPascal,
    propertiesNonCamel,
  };
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

  const docResult = computeDocumentationCompletion(classNodes);
  const namingCompliance = computeNamingCompliance(classNodes);

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
    documentationCompletionPercentage: docResult.percentage,
    classesMissingDocumentation: docResult.classesMissing,
    propertiesMissingDocumentation: docResult.propertiesMissing,
    namingCompliance,
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

/** Per-node heatmap value set for #560 (complexity, change frequency, usage, documentation). */
export interface HeatmapValues {
  /** 0–1: higher = more complex (props + relationships + depth factor). */
  complexity: number;
  /** 0–1: higher = more recently modified (from updated_at). */
  changeRecency: number;
  /** 0–1: higher = more references (degree / max degree). */
  usage: number;
  /** 0–1: higher = better documentation (class + properties with description). */
  documentation: number;
}

/**
 * Compute per-class heatmap values for canvas visualization (#560).
 * Returns a map of node id -> { complexity, changeRecency, usage, documentation } (all 0–1).
 */
export function computeHeatmapValues(nodes: Node[], edges: Edge[]): Map<string, HeatmapValues> {
  const classNodes = getClassNodes(nodes);
  const result = new Map<string, HeatmapValues>();
  if (classNodes.length === 0) return result;

  const degreeMap = getDegreePerNode(classNodes, edges);
  const adj = buildDirectedAdjacency(edges);
  const nodeIds = new Set(classNodes.map((n) => n.id));
  const maxDegree = Math.max(1, ...Array.from(degreeMap.values()));

  // Per-class documentation: class + its properties with non-empty description
  const docPerClass = new Map<string, number>();
  for (const node of classNodes) {
    const data = node.data as {
      name?: string;
      description?: string;
      properties?: Array<{ name?: string; description?: string }>;
    };
    let documented = 0;
    let total = 0;
    total += 1;
    documented += hasDocumentation(data?.description) ? 1 : 0;
    const props = data?.properties;
    if (Array.isArray(props)) {
      for (const p of props) {
        total += 1;
        documented += hasDocumentation(p?.description) ? 1 : 0;
      }
    }
    docPerClass.set(node.id, total === 0 ? 1 : documented / total);
  }

  // Per-class complexity: property count + degree + depth contribution, normalized to 0–1
  const depthFromNode = (nodeId: string): number =>
    longestPathFrom(nodeId, adj, new Set());
  const maxDepth = Math.max(1, ...classNodes.map((n) => depthFromNode(n.id)));
  let maxComplexityRaw = 0;
  const complexityRaw = new Map<string, number>();
  for (const node of classNodes) {
    const propCount = getPropertyCount(node);
    const degree = degreeMap.get(node.id) ?? 0;
    const depth = depthFromNode(node.id);
    const raw = propCount * 2 + degree * 1.5 + depth * 3;
    complexityRaw.set(node.id, raw);
    if (raw > maxComplexityRaw) maxComplexityRaw = raw;
  }
  maxComplexityRaw = Math.max(1, maxComplexityRaw);

  // updated_at timestamps for change recency (optional on node data)
  const timestamps: number[] = [];
  for (const node of classNodes) {
    const updatedAt = (node.data as { updated_at?: string })?.updated_at;
    if (updatedAt) timestamps.push(new Date(updatedAt).getTime());
  }
  const minTs = timestamps.length > 0 ? Math.min(...timestamps) : 0;
  const maxTs = timestamps.length > 1 ? Math.max(...timestamps) - minTs : 1;

  for (const node of classNodes) {
    const usage = (degreeMap.get(node.id) ?? 0) / maxDegree;
    const documentation = docPerClass.get(node.id) ?? 0;
    const complexity = Math.min(1, (complexityRaw.get(node.id) ?? 0) / maxComplexityRaw);
    const updatedAt = (node.data as { updated_at?: string })?.updated_at;
    let changeRecency = 0.5;
    if (updatedAt && maxTs > 0) {
      const t = new Date(updatedAt).getTime();
      changeRecency = (t - minTs) / maxTs;
    }

    result.set(node.id, {
      complexity,
      changeRecency,
      usage,
      documentation,
    });
  }

  return result;
}
