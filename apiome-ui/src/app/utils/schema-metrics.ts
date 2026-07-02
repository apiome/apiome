/**
 * Schema metrics computed from canvas nodes and edges.
 * Used for the Schema Metrics view (#472).
 */

import type { Node, Edge } from '@xyflow/react';
import { detectNamingConvention } from './naming-conventions';
import { buildGraphForSchemaMetrics } from './schema-graph-from-classes';

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
  /** All node IDs that participate in a circular dependency (for canvas warning indicators #548) */
  circularDependencyNodeIds: string[];
  /** Realtime schema complexity score 0–100 (#556) */
  complexityScore: number;
  /** Human-readable complexity band for display */
  complexityLabel: 'Low' | 'Medium' | 'High';
  /** Per-factor contribution for "why is this score" breakdown */
  complexityBreakdown: ComplexityBreakdownItem[];
  /**
   * #612: Sum of cyclomatic-style counts from JSON Schema if/then/else (and nested conditionals)
   * across all class-level schemas and property inline schemas on the canvas.
   */
  conditionalSchemaCyclomaticTotal: number;
  /** Documentation completion 0–100: % of classes and properties with non-empty description (#557) */
  documentationCompletionPercentage: number;
  /** Class names that have no description (for "click to see where coverage is missing") */
  classesMissingDocumentation: string[];
  /** Properties missing description: className + propertyName for display */
  propertiesMissingDocumentation: { className: string; propertyName: string }[];
  /** Naming convention compliance (#558): camelCase, snake_case, PascalCase breakdown */
  namingCompliance: NamingComplianceResult;
  /** #553: Per-class dependency metrics (in-degree, out-degree, betweenness) on dependency graph */
  dependencyMetricsPerClass: DependencyClassMetricsEntry[];
  /**
   * #610: Per-class cognitive complexity for the schema model (AI digest + Studio).
   * Score = property count + weighted sum of outgoing dependency edges (simple refs +1;
   * class-level or property-level allOf +1; anyOf/oneOf +2 as disjunctive load).
   */
  cognitiveComplexityPerClass: CognitiveComplexityPerClassEntry[];
  /** #611: Dependency-only graph complexity (score + drivers). */
  dependencyGraphComplexity: DependencyGraphComplexityReport;
  /** #613: Composite maintainability (higher = easier to evolve). */
  maintainabilityIndex: MaintainabilityIndexReport;
  /** #614: Composite technical debt (higher = more remediation pressure). */
  technicalDebtMetrics: TechnicalDebtMetricsReport;
}

/** #553: One row of dependency metrics for a class (in-degree, out-degree, betweenness). */
export interface DependencyClassMetricsEntry {
  classId: string;
  className: string;
  inDegree: number;
  outDegree: number;
  betweenness: number;
}

/** #610: Cognitive-style load for one class (unbounded integer; higher = more to reason about). */
export interface CognitiveComplexityPerClassEntry {
  classId: string;
  className: string;
  score: number;
  propertyContribution: number;
  referenceContribution: number;
  /** #612: Cyclomatic-style load from if/then/else (and nested) in this class and its property schemas */
  conditionalSchemaCyclomaticContribution: number;
}

/**
 * #611: Aggregate complexity of the dependency-only subgraph ($ref + class allOf/anyOf/oneOf),
 * distinct from the full-canvas relationship count used in the main schema complexity score.
 */
export interface DependencyGraphComplexityReport {
  /** Studio dependency edges (property $ref + class composition edges). */
  edgeCount: number;
  /** Longest path in the dependency digraph (number of edges). */
  deepestChainSteps: number;
  /** Cycle groups (non-trivial SCCs) using only dependency edges. */
  circularGroupCount: number;
  /** 0–100 composite from edges, depth, and cycles on that subgraph. */
  score: number;
  scoreLabel: 'Low' | 'Medium' | 'High';
  /** Factor table for Studio popover and PDF export. */
  breakdown: ComplexityBreakdownItem[];
}

/**
 * #613: Composite maintainability 0–100 (higher = easier to evolve the schema).
 * Blends documentation and naming with inverted structural complexity (#556, #611), with light
 * penalties for mean per-class cognitive load (#610) and wide classes (avg properties/class).
 */
export interface MaintainabilityIndexReport {
  score: number;
  /** Low = harder to maintain; High = easier to maintain. */
  scoreLabel: 'Low' | 'Medium' | 'High';
  breakdown: ComplexityBreakdownItem[];
}

/**
 * #614: Aggregate technical debt 0–100 (higher = more remediation pressure).
 * Composes documentation/naming gaps, structural and dependency load, conditional branching,
 * relationship cycles, chain depth, mean cognitive load, structural isolation, and wide-class pressure.
 */
export interface TechnicalDebtMetricsReport {
  /** 0 = little aggregate debt, 100 = very high debt */
  debtScore: number;
  /** Low / Medium / High severity of aggregate technical debt */
  scoreLabel: 'Low' | 'Medium' | 'High';
  breakdown: ComplexityBreakdownItem[];
}

export function computeTechnicalDebtMetricsReport(input: {
  documentationCompletionPercentage: number;
  namingCompliancePercentage: number;
  complexityScore: number;
  dependencyGraphScore: number;
  conditionalSchemaCyclomaticTotal: number;
  circularDependencyCount: number;
  deepestChainLength: number;
  classCount: number;
  isolatedClassCount: number;
  cognitiveComplexityPerClass: CognitiveComplexityPerClassEntry[];
  averagePropertiesPerClass: number;
}): TechnicalDebtMetricsReport {
  const docGap = Math.min(100, Math.max(0, 100 - input.documentationCompletionPercentage));
  const nameGap = Math.min(100, Math.max(0, 100 - input.namingCompliancePercentage));
  const schemaLoad = Math.min(100, Math.max(0, input.complexityScore));
  const depTangle = Math.min(100, Math.max(0, input.dependencyGraphScore));
  const branchDebt = Math.min(100, Math.max(0, input.conditionalSchemaCyclomaticTotal * 5.5));
  const cycleDebt = Math.min(100, Math.max(0, input.circularDependencyCount * 28));
  const deepDebt = Math.min(100, Math.max(0, input.deepestChainLength * 9));
  const meanCog =
    input.classCount > 0
      ? input.cognitiveComplexityPerClass.reduce((s, r) => s + r.score, 0) / input.classCount
      : 0;
  const cognitiveDebt = Math.min(100, Math.max(0, meanCog * 2.8));
  const orphanDebt =
    input.classCount > 0
      ? Math.min(100, Math.max(0, (input.isolatedClassCount / input.classCount) * 100))
      : 0;
  const sizeExcess = Math.max(0, input.averagePropertiesPerClass - 14);
  const wideClassDebt = Math.min(100, Math.max(0, sizeExcess * 7));

  const wDoc = 0.17;
  const wName = 0.15;
  const wSchema = 0.15;
  const wDep = 0.13;
  const wBranch = 0.11;
  const wCycle = 0.09;
  const wDeep = 0.07;
  const wCog = 0.08;
  const wIso = 0.03;
  const wWide = 0.02;

  const breakdown: ComplexityBreakdownItem[] = [
    {
      label: 'Documentation gap (100 − coverage %)',
      value: Math.round(docGap * 10) / 10,
      weight: wDoc,
      contribution: docGap * wDoc,
    },
    {
      label: 'Naming inconsistency gap (100 − compliance %)',
      value: Math.round(nameGap * 10) / 10,
      weight: wName,
      contribution: nameGap * wName,
    },
    {
      label: 'Aggregate schema complexity load',
      value: schemaLoad,
      weight: wSchema,
      contribution: schemaLoad * wSchema,
    },
    {
      label: 'Dependency graph tangling',
      value: depTangle,
      weight: wDep,
      contribution: depTangle * wDep,
    },
    {
      label: 'Conditional schema branching (cyclomatic, capped)',
      value: Math.round(branchDebt * 10) / 10,
      weight: wBranch,
      contribution: branchDebt * wBranch,
    },
    {
      label: 'Circular dependency groups (capped 0–100)',
      value: Math.round(cycleDebt * 10) / 10,
      weight: wCycle,
      contribution: cycleDebt * wCycle,
    },
    {
      label: 'Deep dependency chains (chain depth, capped 0–100)',
      value: Math.round(deepDebt * 10) / 10,
      weight: wDeep,
      contribution: deepDebt * wDeep,
    },
    {
      label: 'Mean cognitive load per class (capped 0–100)',
      value: Math.round(cognitiveDebt * 10) / 10,
      weight: wCog,
      contribution: cognitiveDebt * wCog,
    },
    {
      label: 'Structurally isolated classes (% of classes, capped 0–100)',
      value: Math.round(orphanDebt * 10) / 10,
      weight: wIso,
      contribution: orphanDebt * wIso,
    },
    {
      label: 'Wide-class pressure (excess properties, capped 0–100)',
      value: Math.round(wideClassDebt * 10) / 10,
      weight: wWide,
      contribution: wideClassDebt * wWide,
    },
  ];

  const raw = breakdown.reduce((s, b) => s + b.contribution, 0);
  const debtScore = Math.min(100, Math.max(0, Math.round(raw)));
  const scoreLabel: TechnicalDebtMetricsReport['scoreLabel'] =
    debtScore >= 67 ? 'High' : debtScore >= 34 ? 'Medium' : 'Low';

  return { debtScore, scoreLabel, breakdown };
}

export function computeMaintainabilityIndexReport(input: {
  documentationCompletionPercentage: number;
  namingCompliancePercentage: number;
  complexityScore: number;
  dependencyGraphScore: number;
  cognitiveComplexityPerClass: CognitiveComplexityPerClassEntry[];
  averagePropertiesPerClass: number;
  classCount: number;
}): MaintainabilityIndexReport {
  const wDoc = 0.32;
  const wNam = 0.28;
  const wInvC = 0.2;
  const wInvD = 0.2;

  const docs = Math.min(100, Math.max(0, input.documentationCompletionPercentage));
  const nam = Math.min(100, Math.max(0, input.namingCompliancePercentage));
  const invC = Math.min(100, Math.max(0, 100 - input.complexityScore));
  const invD = Math.min(100, Math.max(0, 100 - input.dependencyGraphScore));

  const breakdown: ComplexityBreakdownItem[] = [
    { label: 'Documentation', value: docs, weight: wDoc, contribution: docs * wDoc },
    { label: 'Naming consistency', value: nam, weight: wNam, contribution: nam * wNam },
    {
      label: 'Simplicity vs schema complexity',
      value: invC,
      weight: wInvC,
      contribution: invC * wInvC,
    },
    {
      label: 'Simplicity vs dependency graph',
      value: invD,
      weight: wInvD,
      contribution: invD * wInvD,
    },
  ];

  let base = breakdown.reduce((sum, b) => sum + b.contribution, 0);

  const meanCog =
    input.classCount > 0
      ? input.cognitiveComplexityPerClass.reduce((sum, r) => sum + r.score, 0) / input.classCount
      : 0;
  const cognitivePenalty = Math.min(14, meanCog * 0.4);
  if (cognitivePenalty > 0) {
    const mc = Math.round(meanCog * 10) / 10;
    breakdown.push({
      label: 'Cognitive load penalty (mean per class)',
      value: mc,
      weight: 1,
      contribution: -cognitivePenalty,
    });
    base -= cognitivePenalty;
  }

  const sizeExcess =
    input.classCount > 0 ? Math.max(0, input.averagePropertiesPerClass - 14) : 0;
  const sizePenalty = Math.min(10, sizeExcess * 0.55);
  if (sizePenalty > 0) {
    const ap = Math.round(input.averagePropertiesPerClass * 10) / 10;
    breakdown.push({
      label: 'Class size penalty (avg properties/class > 14)',
      value: ap,
      weight: 1,
      contribution: -sizePenalty,
    });
    base -= sizePenalty;
  }

  const score = Math.min(100, Math.max(0, Math.round(base)));
  const scoreLabel: 'Low' | 'Medium' | 'High' =
    score >= 67 ? 'High' : score >= 34 ? 'Medium' : 'Low';

  return { score, scoreLabel, breakdown };
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

function parseJsonIfNeeded(value: unknown): unknown {
  if (typeof value === 'string') {
    try {
      return JSON.parse(value) as unknown;
    } catch {
      return undefined;
    }
  }
  return value;
}

/**
 * #612: Cyclomatic-style count of JSON Schema conditional subschemas (if/then/else).
 * Adds 1 per object with `if`, plus 1 when `else` is present on the same object; recurses into
 * nested keywords (allOf items, then/else branches, etc.).
 */
export function countConditionalSchemaCyclomaticInJsonSchema(schema: unknown): number {
  let total = 0;
  const seen = new WeakSet<object>();

  function walk(node: unknown): void {
    if (node === null || node === undefined) return;
    if (Array.isArray(node)) {
      for (const el of node) walk(el);
      return;
    }
    if (typeof node !== 'object') return;
    if (seen.has(node)) return;
    seen.add(node);

    const obj = node as Record<string, unknown>;
    if ('if' in obj && obj.if !== undefined) {
      total += 1;
      if ('else' in obj && obj.else !== undefined) {
        total += 1;
      }
    }
    for (const key of Object.keys(obj)) {
      walk(obj[key]);
    }
  }

  walk(schema);
  return total;
}

function conditionalSchemaCyclomaticFromClassNode(node: Node): number {
  const data = node.data as { schema?: unknown; properties?: Array<{ data?: unknown }> };
  let n = 0;
  const classSchema = parseJsonIfNeeded(data?.schema);
  if (classSchema !== undefined) {
    n += countConditionalSchemaCyclomaticInJsonSchema(classSchema);
  }
  const props = data?.properties;
  if (Array.isArray(props)) {
    for (const p of props) {
      const pd = parseJsonIfNeeded(p?.data);
      if (pd !== undefined) {
        n += countConditionalSchemaCyclomaticInJsonSchema(pd);
      }
    }
  }
  return n;
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

/** #553: Dependency edges are prop-$ref and allOf/anyOf/oneOf (same classification as editor). */
function isDependencyEdge(e: Edge): boolean {
  const id = e.id ?? '';
  return /^(prop-|allOf-|anyOf-|oneOf-)/.test(id);
}

/**
 * #610: Incremental weight for one outgoing dependency edge toward cognitive complexity.
 * Matches Studio / metrics graph edge id conventions from {@link buildGraphForSchemaMetrics}.
 */
function cognitiveWeightForDependencyEdge(e: Edge): number {
  const id = e.id ?? '';
  if (id.startsWith('anyOf-') || id.startsWith('oneOf-')) return 2;
  if (id.startsWith('allOf-')) return 1;
  if (/^prop-(anyOf|oneOf)-/.test(id)) return 2;
  if (/^prop-allOf-/.test(id)) return 1;
  if (id.startsWith('prop-')) return 1;
  return 0;
}

function computeCognitiveComplexityPerClass(classNodes: Node[], dependencyEdges: Edge[]): CognitiveComplexityPerClassEntry[] {
  const refLoadBySource = new Map<string, number>();
  for (const e of dependencyEdges) {
    if (!isDependencyEdge(e)) continue;
    const w = cognitiveWeightForDependencyEdge(e);
    if (w <= 0) continue;
    refLoadBySource.set(e.source, (refLoadBySource.get(e.source) ?? 0) + w);
  }
  return classNodes.map((n) => {
    const propertyContribution = getPropertyCount(n);
    const referenceContribution = refLoadBySource.get(n.id) ?? 0;
    const conditionalSchemaCyclomaticContribution = conditionalSchemaCyclomaticFromClassNode(n);
    return {
      classId: n.id,
      className: getNodeName(n),
      score: propertyContribution + referenceContribution + conditionalSchemaCyclomaticContribution,
      propertyContribution,
      referenceContribution,
      conditionalSchemaCyclomaticContribution,
    };
  });
}

/**
 * #553: In-degree and out-degree per node for a directed edge set.
 * inDegree[v] = number of edges with target v; outDegree[v] = number of edges with source v.
 */
function getInOutDegreePerNode(
  nodeIds: Set<string>,
  edges: Edge[]
): { inDegree: Map<string, number>; outDegree: Map<string, number> } {
  const inDegree = new Map<string, number>();
  const outDegree = new Map<string, number>();
  for (const id of nodeIds) {
    inDegree.set(id, 0);
    outDegree.set(id, 0);
  }
  for (const e of edges) {
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
    outDegree.set(e.source, (outDegree.get(e.source) ?? 0) + 1);
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
  }
  return { inDegree, outDegree };
}

/**
 * #553: Betweenness centrality (Brandes) for directed unweighted graph.
 * Returns map nodeId -> betweenness (sum over s,t of fraction of shortest s-t paths passing through node).
 */
function computeBetweennessCentrality(
  adj: Map<string, string[]>,
  nodeIds: Set<string>
): Map<string, number> {
  const betweenness = new Map<string, number>();
  for (const id of nodeIds) betweenness.set(id, 0);

  const nodes = Array.from(nodeIds);
  for (const s of nodes) {
    const S: string[] = [];
    const P = new Map<string, string[]>();
    const sigma = new Map<string, number>();
    const d = new Map<string, number>();
    for (const id of nodeIds) {
      P.set(id, []);
      sigma.set(id, 0);
      d.set(id, -1);
    }
    sigma.set(s, 1);
    d.set(s, 0);
    const Q: string[] = [s];

    while (Q.length > 0) {
      const v = Q.shift()!;
      S.push(v);
      for (const w of adj.get(v) ?? []) {
        if (!nodeIds.has(w)) continue;
        if (d.get(w)! < 0) {
          Q.push(w);
          d.set(w, d.get(v)! + 1);
        }
        if (d.get(w) === d.get(v)! + 1) {
          sigma.set(w, (sigma.get(w) ?? 0) + (sigma.get(v) ?? 0));
          P.get(w)!.push(v);
        }
      }
    }

    const delta = new Map<string, number>();
    for (const id of nodeIds) delta.set(id, 0);
    while (S.length > 0) {
      const w = S.pop()!;
      for (const v of P.get(w) ?? []) {
        const sigmaW = sigma.get(w) ?? 1;
        const sigmaV = sigma.get(v) ?? 0;
        delta.set(
          v,
          (delta.get(v) ?? 0) + (sigmaW > 0 ? (sigmaV / sigmaW) * (1 + (delta.get(w) ?? 0)) : 0)
        );
      }
      if (w !== s) {
        betweenness.set(w, (betweenness.get(w) ?? 0) + (delta.get(w) ?? 0));
      }
    }
  }
  return betweenness;
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
 * Returns count, sample node IDs, and the list of circular SCCs (for #548 canvas indicators).
 */
function countCircularDependencies(adj: Map<string, string[]>, nodeIds: Set<string>): {
  count: number;
  sampleNodeIds: string[];
  circularSccs: string[][];
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
  return { count: circularSccs.length, sampleNodeIds, circularSccs };
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
 * Compute schema metrics from persisted class rows (same shape as the studio canvas API) — #323 timeline.
 */
export function computeSchemaMetricsFromClasses(classes: unknown[]): SchemaMetricsResult {
  const { nodes, edges } = buildGraphForSchemaMetrics(classes);
  return computeSchemaMetrics(nodes, edges);
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
  const { count: circularDependencyCount, sampleNodeIds, circularSccs } = countCircularDependencies(adj, nodeIds);
  const circularSampleNames = sampleNodeIds
    .map((id) => idToNode.get(id))
    .filter(Boolean)
    .map((n) => getNodeName(n!));
  const circularDependencyNodeIds = circularSccs.flat();

  const conditionalSchemaCyclomaticTotal = classNodes.reduce(
    (sum, n) => sum + conditionalSchemaCyclomaticFromClassNode(n),
    0
  );

  const { complexityScore, complexityLabel, complexityBreakdown } = computeComplexityScoreFromAggregates({
    classCount,
    totalProperties,
    averagePropertiesPerClass,
    relationshipCount: edges.length,
    deepestChainLength,
    circularDependencyCount,
    conditionalSchemaCyclomatic: conditionalSchemaCyclomaticTotal,
  });

  const docResult = computeDocumentationCompletion(classNodes);
  const namingCompliance = computeNamingCompliance(classNodes);

  // #553: Dependency metrics per class (in-degree, out-degree, betweenness) on dependency graph only
  const dependencyEdges = edges.filter(isDependencyEdge);
  const depAdj = buildDirectedAdjacency(dependencyEdges);
  const { inDegree: inDegreeMap, outDegree: outDegreeMap } = getInOutDegreePerNode(nodeIds, dependencyEdges);
  const betweennessMap = computeBetweennessCentrality(depAdj, nodeIds);
  const dependencyMetricsPerClass: DependencyClassMetricsEntry[] = classNodes.map((n) => ({
    classId: n.id,
    className: getNodeName(n),
    inDegree: inDegreeMap.get(n.id) ?? 0,
    outDegree: outDegreeMap.get(n.id) ?? 0,
    betweenness: betweennessMap.get(n.id) ?? 0,
  }));

  const cognitiveComplexityPerClass = computeCognitiveComplexityPerClass(classNodes, dependencyEdges);
  const dependencyGraphComplexity = computeDependencyGraphComplexityReport(nodeIds, dependencyEdges);

  const maintainabilityIndex = computeMaintainabilityIndexReport({
    documentationCompletionPercentage: docResult.percentage,
    namingCompliancePercentage: namingCompliance.compliancePercentage,
    complexityScore,
    dependencyGraphScore: dependencyGraphComplexity.score,
    cognitiveComplexityPerClass,
    averagePropertiesPerClass,
    classCount,
  });

  const technicalDebtMetrics = computeTechnicalDebtMetricsReport({
    documentationCompletionPercentage: docResult.percentage,
    namingCompliancePercentage: namingCompliance.compliancePercentage,
    complexityScore,
    dependencyGraphScore: dependencyGraphComplexity.score,
    conditionalSchemaCyclomaticTotal,
    circularDependencyCount,
    deepestChainLength,
    classCount,
    isolatedClassCount: isolatedClassIds.length,
    cognitiveComplexityPerClass,
    averagePropertiesPerClass,
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
    circularDependencyNodeIds,
    complexityScore,
    complexityLabel,
    complexityBreakdown,
    conditionalSchemaCyclomaticTotal,
    documentationCompletionPercentage: docResult.percentage,
    classesMissingDocumentation: docResult.classesMissing,
    propertiesMissingDocumentation: docResult.propertiesMissing,
    namingCompliance,
    dependencyMetricsPerClass,
    cognitiveComplexityPerClass,
    dependencyGraphComplexity,
    maintainabilityIndex,
    technicalDebtMetrics,
  };
}

/**
 * #550: Compute all class IDs that would be affected when the given class is changed.
 * "Affected" = classes that (directly or transitively) reference the selected class
 * via dependency edges ($ref, allOf/anyOf/oneOf). Uses reverse dependency graph and BFS.
 */
export function getAffectedClassIds(
  selectedNodeId: string,
  nodes: Node[],
  dependencyEdges: Edge[]
): Set<string> {
  const classNodes = getClassNodes(nodes);
  const nodeIds = new Set(classNodes.map((n) => n.id));
  if (!nodeIds.has(selectedNodeId)) return new Set();

  // Reverse adjacency: for edge source -> target, "target" is the changed class, "source" is affected
  const reverseAdj = new Map<string, string[]>();
  for (const e of dependencyEdges) {
    const src = e.source;
    const tgt = e.target;
    if (!nodeIds.has(src) || !nodeIds.has(tgt)) continue;
    if (!reverseAdj.has(tgt)) reverseAdj.set(tgt, []);
    reverseAdj.get(tgt)!.push(src);
  }

  const affected = new Set<string>();
  const queue: string[] = [selectedNodeId];
  const visited = new Set<string>([selectedNodeId]);

  while (queue.length > 0) {
    const cur = queue.shift()!;
    for (const next of reverseAdj.get(cur) ?? []) {
      if (visited.has(next)) continue;
      visited.add(next);
      affected.add(next);
      queue.push(next);
    }
  }
  return affected;
}

/**
 * #551: Compute all class IDs that the given class depends on (upstream dependencies).
 * "Upstream" = classes that the selected class (directly or transitively) references
 * via dependency edges ($ref, allOf/anyOf/oneOf). Forward BFS from selected node.
 */
export function getUpstreamClassIds(
  selectedNodeId: string,
  nodes: Node[],
  dependencyEdges: Edge[]
): Set<string> {
  const classNodes = getClassNodes(nodes);
  const nodeIds = new Set(classNodes.map((n) => n.id));
  if (!nodeIds.has(selectedNodeId)) return new Set();

  const adj = new Map<string, string[]>();
  for (const e of dependencyEdges) {
    const src = e.source;
    const tgt = e.target;
    if (!nodeIds.has(src) || !nodeIds.has(tgt)) continue;
    if (!adj.has(src)) adj.set(src, []);
    adj.get(src)!.push(tgt);
  }

  const upstream = new Set<string>();
  const queue: string[] = [selectedNodeId];
  const visited = new Set<string>([selectedNodeId]);

  while (queue.length > 0) {
    const cur = queue.shift()!;
    for (const next of adj.get(cur) ?? []) {
      if (visited.has(next)) continue;
      visited.add(next);
      upstream.add(next);
      queue.push(next);
    }
  }
  return upstream;
}

/**
 * #552: Compute the full dependency chain for a focal node: all nodes and dependency edges
 * that are on any path through the focal (upstream ∪ downstream ∪ focal, and edges between them).
 * Used for "Trace full chain" path highlighting on the canvas.
 */
export function getDependencyChainNodeAndEdgeIds(
  focalNodeId: string,
  nodes: Node[],
  dependencyEdges: Edge[]
): { nodeIds: Set<string>; edgeIds: Set<string> } {
  const upstream = getUpstreamClassIds(focalNodeId, nodes, dependencyEdges);
  const downstream = getAffectedClassIds(focalNodeId, nodes, dependencyEdges);
  const nodeIds = new Set<string>([focalNodeId, ...upstream, ...downstream]);

  const edgeIds = new Set<string>();
  for (const e of dependencyEdges) {
    if (nodeIds.has(e.source) && nodeIds.has(e.target)) edgeIds.add(e.id);
  }
  return { nodeIds, edgeIds };
}

/**
 * Returns the set of edge IDs that are part of a circular dependency (#548).
 * Used by the canvas to highlight circular dependency edges with warning styling.
 */
export function getCircularDependencyEdgeIds(nodes: Node[], edges: Edge[]): Set<string> {
  const classNodes = getClassNodes(nodes);
  const nodeIds = new Set(classNodes.map((n) => n.id));
  const adj = buildDirectedAdjacency(edges);
  const { circularSccs } = countCircularDependencies(adj, nodeIds);
  const edgeIds = new Set<string>();
  for (const e of edges) {
    const inSameScc = circularSccs.some((scc) => scc.includes(e.source) && scc.includes(e.target));
    if (inSameScc) edgeIds.add(e.id);
  }
  return edgeIds;
}

/**
 * Compute dependency depth for each class node (#549).
 * Uses only the provided dependency edges (e.g. prop-/allOf-/anyOf-/oneOf-).
 * Depth = distance from "leaves" (nodes with no outgoing dependency edges):
 * - 0 = leaf (does not depend on any other class)
 * - 1 = 1st degree (depends only on leaves)
 * - 2 = 2nd degree, 3 = 3rd degree, etc.
 * Returns a map nodeId -> depth (0, 1, 2, 3, 4, ...).
 */
export function getDependencyDepthMap(
  nodes: Node[],
  dependencyEdges: Edge[]
): Map<string, number> {
  const classNodes = getClassNodes(nodes);
  const nodeIds = new Set(classNodes.map((n) => n.id));
  const adj = buildDirectedAdjacency(dependencyEdges);
  const depth = new Map<string, number>();
  for (const id of nodeIds) depth.set(id, 0);

  let changed = true;
  for (let iter = 0; changed && iter < (nodeIds.size + 2); iter++) {
    changed = false;
    for (const id of nodeIds) {
      const refs = adj.get(id);
      if (!refs || refs.length === 0) continue;
      const maxRefDepth = Math.max(
        ...refs.filter((t) => nodeIds.has(t)).map((t) => depth.get(t) ?? 0)
      );
      const newDepth = 1 + maxRefDepth;
      if (newDepth !== depth.get(id)) {
        depth.set(id, newDepth);
        changed = true;
      }
    }
  }
  return depth;
}

/** Inputs for {@link computeComplexityScoreFromAggregates} (project-wide or per-class local subgraph). */
export type AggregateComplexityMetrics = {
  classCount: number;
  totalProperties: number;
  averagePropertiesPerClass: number;
  relationshipCount: number;
  deepestChainLength: number;
  circularDependencyCount: number;
  /** #612: Cyclomatic-style aggregate from if/then/else across the measured subgraph */
  conditionalSchemaCyclomatic: number;
};

/**
 * Compute a 0–100 schema complexity score, label, and per-factor breakdown (#556).
 * Based on class count, property count, relationships, depth, and cycles.
 * Also used for per-class local metrics (#250).
 */
export function computeComplexityScoreFromAggregates(metrics: AggregateComplexityMetrics): {
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
    conditionalSchemaCyclomatic: 2,
  };
  const cyclo = metrics.conditionalSchemaCyclomatic;
  const breakdown: ComplexityBreakdownItem[] = [
    { label: 'Classes', value: metrics.classCount, weight: weights.classCount, contribution: metrics.classCount * weights.classCount },
    { label: 'Total properties', value: metrics.totalProperties, weight: weights.totalProperties, contribution: metrics.totalProperties * weights.totalProperties },
    { label: 'Relationships', value: metrics.relationshipCount, weight: weights.relationshipCount, contribution: metrics.relationshipCount * weights.relationshipCount },
    { label: 'Avg properties/class', value: metrics.averagePropertiesPerClass, weight: weights.averagePropertiesPerClass, contribution: metrics.averagePropertiesPerClass * weights.averagePropertiesPerClass },
    { label: 'Deepest chain (steps)', value: metrics.deepestChainLength, weight: weights.deepestChainLength, contribution: metrics.deepestChainLength * weights.deepestChainLength },
    { label: 'Circular dependencies', value: metrics.circularDependencyCount, weight: weights.circularDependencyCount, contribution: metrics.circularDependencyCount * weights.circularDependencyCount },
    {
      label: 'Conditional schema cyclomatic (#612)',
      value: cyclo,
      weight: weights.conditionalSchemaCyclomatic,
      contribution: cyclo * weights.conditionalSchemaCyclomatic,
    },
  ];
  const raw = breakdown.reduce((sum, b) => sum + b.contribution, 0);
  const complexityScore = Math.min(100, Math.max(0, Math.round(raw)));
  const complexityLabel: 'Low' | 'Medium' | 'High' =
    complexityScore <= 33 ? 'Low' : complexityScore <= 66 ? 'Medium' : 'High';
  return { complexityScore, complexityLabel, complexityBreakdown: breakdown };
}

/**
 * #611: Score how tangled the dependency-only graph is (refs + composition), using the same
 * weight scale as the structural slice of {@link computeComplexityScoreFromAggregates}
 * (edges × 1.2, deepest chain × 4, cycles × 6), capped to 0–100.
 */
export function computeDependencyGraphComplexityReport(
  nodeIds: Set<string>,
  dependencyEdges: Edge[]
): DependencyGraphComplexityReport {
  const edgeCount = dependencyEdges.length;
  const depAdj = buildDirectedAdjacency(dependencyEdges);
  const deepestChainSteps =
    nodeIds.size === 0 ? 0 : computeDeepestChain(depAdj, nodeIds);
  const { count: circularGroupCount } = countCircularDependencies(depAdj, nodeIds);

  const wEdge = 1.2;
  const wDepth = 4;
  const wCycle = 6;
  const breakdown: ComplexityBreakdownItem[] = [
    {
      label: 'Dependency edges',
      value: edgeCount,
      weight: wEdge,
      contribution: edgeCount * wEdge,
    },
    {
      label: 'Deepest ref chain (steps)',
      value: deepestChainSteps,
      weight: wDepth,
      contribution: deepestChainSteps * wDepth,
    },
    {
      label: 'Circular groups (deps)',
      value: circularGroupCount,
      weight: wCycle,
      contribution: circularGroupCount * wCycle,
    },
  ];
  const raw = breakdown.reduce((sum, b) => sum + b.contribution, 0);
  const score = Math.min(100, Math.max(0, Math.round(raw)));
  const scoreLabel: 'Low' | 'Medium' | 'High' =
    score <= 33 ? 'Low' : score <= 66 ? 'Medium' : 'High';
  return {
    edgeCount,
    deepestChainSteps,
    circularGroupCount,
    score,
    scoreLabel,
    breakdown,
  };
}

/** One class (schema) row for version scoring breakdown (#250). */
export interface PerSchemaScoreRow {
  classId: string;
  className: string;
  /** 0–100: class + properties with non-empty descriptions */
  documentationScore: number;
  /** 0–100: PascalCase class name and camelCase property names */
  namingScore: number;
  /** 0–100: aggregate complexity model applied to this class’s local stats */
  complexityScore: number;
  complexityLabel: 'Low' | 'Medium' | 'High';
}

function computeDocumentationScoreForClass(node: Node): number {
  const data = node.data as {
    description?: string;
    properties?: Array<{ description?: string }>;
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
  return total === 0 ? 100 : Math.round((documented / total) * 100);
}

function computeNamingScoreForClass(node: Node): number {
  const data = node.data as {
    name?: string;
    properties?: Array<{ name?: string }>;
  };
  const className = typeof data?.name === 'string' ? data.name : node.id;
  let compliant = 0;
  let total = 0;
  total += 1;
  compliant += detectNamingConvention(className) === 'PascalCase' ? 1 : 0;
  const props = data?.properties;
  if (Array.isArray(props)) {
    for (const p of props) {
      total += 1;
      const propName = typeof p?.name === 'string' ? p.name.trim() : '';
      compliant += propName !== '' && detectNamingConvention(propName) === 'camelCase' ? 1 : 0;
    }
  }
  return total === 0 ? 100 : Math.round((compliant / total) * 100);
}

/**
 * Per-class documentation, naming, and complexity scores for the current graph (#250).
 * Complexity uses the same weighted aggregate model as the project-wide score, with local counts.
 */
export function computePerSchemaScores(nodes: Node[], edges: Edge[]): PerSchemaScoreRow[] {
  const classNodes = getClassNodes(nodes);
  if (classNodes.length === 0) return [];

  const degreeMap = getDegreePerNode(classNodes, edges);
  const adj = buildDirectedAdjacency(edges);
  const nodeIds = new Set(classNodes.map((n) => n.id));
  const { circularSccs } = countCircularDependencies(adj, nodeIds);
  const inCycle = new Set<string>();
  for (const scc of circularSccs) {
    for (const id of scc) inCycle.add(id);
  }

  // Pre-compute longest-path depths for all nodes in a single DFS pass (memoized).
  // This avoids O(N * (N+E)) repeated calls by sharing memo across all starting nodes.
  const depthMemo = new Map<string, number>();
  function longestPathMemo(nodeId: string, visitedInPath: Set<string>): number {
    if (visitedInPath.has(nodeId)) return 0;
    if (depthMemo.has(nodeId)) return depthMemo.get(nodeId)!;
    const next = adj.get(nodeId);
    if (!next || next.length === 0) {
      depthMemo.set(nodeId, 0);
      return 0;
    }
    visitedInPath.add(nodeId);
    let max = 0;
    for (const t of next) {
      const d = 1 + longestPathMemo(t, visitedInPath);
      if (d > max) max = d;
    }
    visitedInPath.delete(nodeId);
    depthMemo.set(nodeId, max);
    return max;
  }
  for (const n of classNodes) {
    longestPathMemo(n.id, new Set());
  }

  const rows: PerSchemaScoreRow[] = classNodes.map((n) => {
    const className = getNodeName(n);
    const props = getPropertyCount(n);
    const degree = degreeMap.get(n.id) ?? 0;
    const chainLen = depthMemo.get(n.id) ?? 0;
    const conditionalSchemaCyclomatic = conditionalSchemaCyclomaticFromClassNode(n);
    const { complexityScore, complexityLabel } = computeComplexityScoreFromAggregates({
      classCount: 1,
      totalProperties: props,
      averagePropertiesPerClass: props,
      relationshipCount: degree,
      deepestChainLength: chainLen,
      circularDependencyCount: inCycle.has(n.id) ? 1 : 0,
      conditionalSchemaCyclomatic,
    });
    return {
      classId: n.id,
      className,
      documentationScore: computeDocumentationScoreForClass(n),
      namingScore: computeNamingScoreForClass(n),
      complexityScore,
      complexityLabel,
    };
  });

  rows.sort((a, b) => a.className.localeCompare(b.className));
  return rows;
}

/**
 * Per-class scores from persisted class rows (same shape as studio / timeline APIs) (#250).
 */
export function computePerSchemaScoresFromClasses(classes: unknown[]): PerSchemaScoreRow[] {
  const { nodes, edges } = buildGraphForSchemaMetrics(classes);
  return computePerSchemaScores(nodes, edges);
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
