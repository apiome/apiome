/**
 * Canvas improvement suggestions (#474).
 * Computes actionable suggestions from schema metrics, layout quality, and graph structure.
 */

import type { Node, Edge } from '@xyflow/react';
import type { LayoutQualityResult } from '@/app/utils/layout-quality';
import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';
import { analyzeCanvasLayoutGraph } from '@/app/utils/canvas-layout-graph-analysis';

export type CanvasSuggestionKind =
  | 'recommended_layout_direction'
  | 'strongly_connected_canvas'
  | 'canvas_hub_layout'
  | 'hierarchy_roots_layout'
  | 'weakly_disconnected_canvas'
  | 'reduce_edge_crossings'
  | 'group_related'
  | 'isolated_class'
  | 'split_cluster'
  | 'extract_inline_properties';

export interface CanvasSuggestion {
  id: string;
  kind: CanvasSuggestionKind;
  title: string;
  description: string;
  /** Optional detail (e.g. class names, count) for display */
  detail?: string;
  /** Optional action for the UI (e.g. apply layout, focus nodes) */
  action?: {
    type: 'apply_hierarchical_layout';
    direction?: 'TB' | 'LR';
  };
}

const EDGE_CROSSING_THRESHOLD = 3;
const LARGE_CLUSTER_SIZE = 10;
const RELATED_GROUP_MIN = 3;
const RELATED_GROUP_MAX = 9;
const INLINE_PROPERTIES_THRESHOLD = 6;

function getClassNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) => n.type !== 'groupNode');
}

function getNodeName(node: Node): string {
  const name = (node.data as { name?: string })?.name;
  return typeof name === 'string' ? name : node.id;
}

function getProperties(node: Node): { id: string; data: unknown }[] {
  const props = (node.data as { properties?: { id: string; data: unknown }[] })?.properties;
  return Array.isArray(props) ? props : [];
}

function isReferenceProperty(propData: Record<string, unknown> | null): boolean {
  if (!propData) return false;
  if (propData.$ref) return true;
  const type = Array.isArray(propData.type) ? propData.type.find((t) => t !== 'null') : propData.type;
  if (type === 'array' && propData.items && typeof propData.items === 'object') {
    return !!(propData.items as Record<string, unknown>).$ref;
  }
  return false;
}

function countInlineProperties(node: Node): number {
  const props = getProperties(node);
  let count = 0;
  for (const prop of props) {
    const data = typeof prop.data === 'string' ? (JSON.parse(prop.data) as Record<string, unknown>) : (prop.data as Record<string, unknown>);
    if (!isReferenceProperty(data)) count++;
  }
  return count;
}

/** Undirected adjacency for connected components */
function buildUndirectedAdjacency(edges: Edge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  for (const e of edges) {
    const a = e.source;
    const b = e.target;
    if (!adj.has(a)) adj.set(a, new Set());
    if (!adj.has(b)) adj.set(b, new Set());
    adj.get(a)!.add(b);
    adj.get(b)!.add(a);
  }
  return adj;
}

function getConnectedComponents(
  nodeIds: Set<string>,
  adj: Map<string, Set<string>>
): string[][] {
  const visited = new Set<string>();
  const components: string[][] = [];

  function dfs(id: string, component: string[]): void {
    if (visited.has(id)) return;
    visited.add(id);
    component.push(id);
    for (const neighbor of adj.get(id) ?? []) {
      if (nodeIds.has(neighbor)) dfs(neighbor, component);
    }
  }

  for (const id of nodeIds) {
    if (visited.has(id)) continue;
    const component: string[] = [];
    dfs(id, component);
    components.push(component);
  }
  return components;
}

export interface ComputeSuggestionsInput {
  nodes: Node[];
  edges: Edge[];
  metrics: SchemaMetricsResult | null;
  layoutQuality: LayoutQualityResult | null;
  /** Node IDs that are already inside a group (optional, to avoid suggesting "group" for already grouped) */
  groupMemberIds?: Set<string>;
}

/**
 * Compute canvas improvement suggestions from current nodes, edges, metrics, and layout quality.
 */
export function computeCanvasSuggestions(input: ComputeSuggestionsInput): CanvasSuggestion[] {
  const { nodes, edges, metrics, layoutQuality, groupMemberIds } = input;
  const suggestions: CanvasSuggestion[] = [];
  const classNodes = getClassNodes(nodes);
  const idToNode = new Map(classNodes.map((n) => [n.id, n]));
  const nodeIds = new Set(classNodes.map((n) => n.id));
  const adj = buildUndirectedAdjacency(edges);
  const components = getConnectedComponents(nodeIds, adj);

  const layoutAnalysis = analyzeCanvasLayoutGraph(nodes, edges, {
    deepestDependencyChainLength: metrics?.deepestChainLength ?? null,
  });

  if (layoutAnalysis && layoutAnalysis.classCount >= 2) {
    const dir = layoutAnalysis.recommendedDirection;
    const dirLabel = dir === 'TB' ? 'Top → Bottom' : 'Left → Right';
    suggestions.push({
      id: 'suggest-layout-direction-analysis',
      kind: 'recommended_layout_direction',
      title: `Recommended auto-layout: ${dirLabel}`,
      description: layoutAnalysis.recommendationReason,
      detail: `Pseudo depth ${layoutAnalysis.pseudoLayerDepth}, max width ${layoutAnalysis.pseudoLayerMaxWidth}${
        layoutAnalysis.nonTrivialSccCount ? ` · ${layoutAnalysis.nonTrivialSccCount} cyclic SCC(s)` : ''
      }`,
      action: { type: 'apply_hierarchical_layout', direction: dir },
    });

    const cyclicComponents = layoutAnalysis.stronglyConnectedComponents.filter((s) => s.memberIds.length > 1);
    for (let i = 0; i < Math.min(3, cyclicComponents.length); i++) {
      const scc = cyclicComponents[i];
      const preview = scc.memberNames.slice(0, 6).join(', ');
      const extra = scc.memberNames.length > 6 ? ` +${scc.memberNames.length - 6} more` : '';
      suggestions.push({
        id: `suggest-scc-${scc.memberIds.slice().sort().join('-').slice(0, 48)}`,
        kind: 'strongly_connected_canvas',
        title: `Directed cycle cluster (${scc.memberIds.length} classes)`,
        description:
          'These classes reach each other along directed canvas edges — a tightly coupled subgraph. Consider grouping them or emphasizing them near the layout anchor.',
        detail: `${preview}${extra}`,
      });
    }

    const topHub = layoutAnalysis.hubClasses[0];
    if (topHub && topHub.totalDegree >= 4 && layoutAnalysis.vertexCount >= 3) {
      const others = layoutAnalysis.hubClasses
        .slice(1, 4)
        .map((h) => h.name)
        .filter(Boolean);
      suggestions.push({
        id: `suggest-canvas-hub-${topHub.id}`,
        kind: 'canvas_hub_layout',
        title: `${topHub.name} is a canvas hub`,
        description:
          'High in + out degree on the canvas graph — place it centrally or use it as a backbone when you run auto-layout.',
        detail: others.length ? `Also busy: ${others.join(', ')}` : `${topHub.inDegree} in · ${topHub.outDegree} out`,
      });
    }

    if (layoutAnalysis.hierarchyRoots.length > 0 && edges.length > 0) {
      const roots = layoutAnalysis.hierarchyRoots;
      const names = roots.slice(0, 10).map((r) => r.name);
      suggestions.push({
        id: 'suggest-hierarchy-roots',
        kind: 'hierarchy_roots_layout',
        title:
          roots.length === 1
            ? `${roots[0].name} is a hierarchy root`
            : `${roots.length} hierarchy roots on the canvas`,
        description:
          'No incoming canvas edges — good anchors at the top (TB) or left (LR) when running hierarchical layout.',
        detail: names.join(', ') + (roots.length > 10 ? ` +${roots.length - 10} more` : ''),
        action: { type: 'apply_hierarchical_layout', direction: layoutAnalysis.recommendedDirection },
      });
    }

    if (layoutAnalysis.weaklyConnectedComponentCount > 1 && edges.length > 0) {
      suggestions.push({
        id: 'suggest-weak-components',
        kind: 'weakly_disconnected_canvas',
        title: `${layoutAnalysis.weaklyConnectedComponentCount} disconnected subgraphs`,
        description:
          'Relationship islands detected — arrange clusters separately or run auto-layout per island for clearer structure.',
        detail: 'Uses undirected canvas edges between classes/groups.',
        action: { type: 'apply_hierarchical_layout', direction: layoutAnalysis.recommendedDirection },
      });
    }
  }

  // 1. Reduce edge crossings by switching layout
  if (layoutQuality && layoutQuality.edgeCrossingCount >= EDGE_CROSSING_THRESHOLD) {
    const crossingDir = layoutAnalysis?.recommendedDirection ?? 'TB';
    suggestions.push({
      id: 'suggest-reduce-edge-crossings',
      kind: 'reduce_edge_crossings',
      title: 'Reduce edge crossings',
      description: 'Try a different layout direction (e.g. Top↔Bottom or Left↔Right) or use Auto-organize to improve readability.',
      detail: `${layoutQuality.edgeCrossingCount} crossing${layoutQuality.edgeCrossingCount !== 1 ? 's' : ''} detected.`,
      action: { type: 'apply_hierarchical_layout', direction: crossingDir },
    });
  }

  // 2. Group related classes (connected component of size in [RELATED_GROUP_MIN, RELATED_GROUP_MAX])
  for (const component of components) {
    const size = component.length;
    if (size < RELATED_GROUP_MIN || size > RELATED_GROUP_MAX) continue;
    const alreadyGrouped = groupMemberIds ? component.every((id) => groupMemberIds.has(id)) : false;
    if (alreadyGrouped) continue;
    const names = component
      .map((id) => getNodeName(idToNode.get(id)!))
      .filter(Boolean)
      .slice(0, 5);
    const nameList = names.length === size ? names.join(', ') : `${names.join(', ')} and ${size - names.length} more`;
    suggestions.push({
      id: `suggest-group-${component.slice(0, 3).join('-')}`,
      kind: 'group_related',
      title: `Group these ${size} classes`,
      description: "They're all connected – consider grouping them for a clearer canvas.",
      detail: nameList,
    });
  }

  // 3. Isolated classes
  if (metrics && metrics.isolatedNames.length > 0) {
    for (let i = 0; i < metrics.isolatedNames.length; i++) {
      const name = metrics.isolatedNames[i];
      const nodeId = metrics.isolatedClassIds[i];
      suggestions.push({
        id: `suggest-isolated-${nodeId}`,
        kind: 'isolated_class',
        title: `${name} is isolated`,
        description: 'Consider adding relationships (reference properties) to other classes.',
        detail: 'No edges connect this class.',
      });
    }
  }

  // 4. Large clusters – suggest splitting
  for (const component of components) {
    if (component.length < LARGE_CLUSTER_SIZE) continue;
    const names = component
      .map((id) => getNodeName(idToNode.get(id)!))
      .filter(Boolean)
      .slice(0, 3);
    suggestions.push({
      id: `suggest-split-cluster-${component[0]}`,
      kind: 'split_cluster',
      title: 'Large cluster detected',
      description: `This connected group has ${component.length} classes. Consider splitting into smaller groups for clarity.`,
      detail: names.length ? `e.g. ${names.join(', ')}…` : undefined,
    });
  }

  // 5. Large set of inline properties – suggest extracting to references
  for (const node of classNodes) {
    const inlineCount = countInlineProperties(node);
    if (inlineCount < INLINE_PROPERTIES_THRESHOLD) continue;
    const name = getNodeName(node);
    suggestions.push({
      id: `suggest-extract-inline-${node.id}`,
      kind: 'extract_inline_properties',
      title: `${name} has many inline properties`,
      description: 'Consider extracting some properties into separate classes and referencing them to simplify the schema.',
      detail: `${inlineCount} inline properties (non-reference).`,
    });
  }

  return suggestions;
}
