/**
 * Canvas / ReactFlow layout graph analysis (#623).
 * Directed strongly connected components, hierarchy roots, hubs, and layout direction hints.
 */

import type { Edge, Node } from '@xyflow/react';
import { stableStringify } from '@lib/stable-json';

export interface CanvasLayoutHubEntry {
  id: string;
  name: string;
  inDegree: number;
  outDegree: number;
  totalDegree: number;
}

export interface CanvasLayoutSccEntry {
  memberIds: string[];
  memberNames: string[];
}

export interface CanvasLayoutRootEntry {
  id: string;
  name: string;
}

export interface CanvasLayoutGraphAnalysis {
  classCount: number;
  edgeCount: number;
  /** Vertices after collapsing grouped classes into group nodes (matches auto-layout graph). */
  vertexCount: number;
  recommendedDirection: 'TB' | 'LR';
  recommendationReason: string;
  stronglyConnectedComponents: CanvasLayoutSccEntry[];
  nonTrivialSccCount: number;
  hubClasses: CanvasLayoutHubEntry[];
  hierarchyRoots: CanvasLayoutRootEntry[];
  weaklyConnectedComponentCount: number;
  pseudoLayerDepth: number;
  pseudoLayerMaxWidth: number;
}

function compareLabels(a: string, b: string): number {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function buildVertexLabelMap(nodes: Node[]): Map<string, string> {
  const labels = new Map<string, string>();
  for (const n of nodes) {
    const d = n.data as { name?: string; label?: string } | undefined;
    const label = typeof d?.label === 'string' ? d.label.trim() : '';
    const name = typeof d?.name === 'string' ? d.name.trim() : '';
    labels.set(n.id, name || label || n.id);
  }
  return labels;
}

function getVertexLabel(vertexLabels: Map<string, string>, id: string): string {
  return vertexLabels.get(id) ?? id;
}

function buildAdjacencyMaps(edges: Array<{ source: string; target: string }>): {
  outgoing: Map<string, string[]>;
  incoming: Map<string, string[]>;
} {
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  for (const e of edges) {
    const os = outgoing.get(e.source) ?? [];
    os.push(e.target);
    outgoing.set(e.source, os);
    const ins = incoming.get(e.target) ?? [];
    ins.push(e.source);
    incoming.set(e.target, ins);
  }
  return { outgoing, incoming };
}

/** Same layering idea as canvas-auto-layout: roots at 0, longest path layering. */
function assignPseudoLayers(
  vertexIds: string[],
  adj: { outgoing: Map<string, string[]>; incoming: Map<string, string[]> }
): Map<string, number> {
  const layers = new Map<string, number>();
  const unreachable = Number.NEGATIVE_INFINITY;
  for (const id of vertexIds) layers.set(id, unreachable);

  const rootNodes = vertexIds.filter((id) => (adj.incoming.get(id) ?? []).length === 0);

  let seeds = rootNodes;
  if (seeds.length === 0 && vertexIds.length > 0) {
    let minIncoming = Infinity;
    let minNode = vertexIds[0];
    for (const id of vertexIds) {
      const inc = (adj.incoming.get(id) ?? []).length;
      if (inc < minIncoming) {
        minIncoming = inc;
        minNode = id;
      }
    }
    seeds = [minNode];
  }

  for (const id of seeds) layers.set(id, 0);

  // Iterative longest-path relaxation from chosen seeds.
  for (let i = 0; i < vertexIds.length - 1; i += 1) {
    let changed = false;
    for (const sourceId of vertexIds) {
      const sourceLayer = layers.get(sourceId) ?? unreachable;
      if (!Number.isFinite(sourceLayer)) continue;
      const nextLayer = sourceLayer + 1;
      for (const targetId of adj.outgoing.get(sourceId) ?? []) {
        const targetLayer = layers.get(targetId) ?? unreachable;
        if (nextLayer > targetLayer) {
          layers.set(targetId, nextLayer);
          changed = true;
        }
      }
    }
    if (!changed) break;
  }

  for (const id of vertexIds) {
    if (!Number.isFinite(layers.get(id) ?? unreachable)) layers.set(id, 0);
  }

  return layers;
}

function layerDepthAndMaxWidth(layerAssignments: Map<string, number>): { depth: number; maxWidth: number } {
  const byLayer = new Map<number, number>();
  layerAssignments.forEach((layer) => {
    byLayer.set(layer, (byLayer.get(layer) ?? 0) + 1);
  });
  const depth =
    byLayer.size === 0 ? 0 : Math.max(...Array.from(byLayer.keys())) - Math.min(...Array.from(byLayer.keys())) + 1;
  const maxWidth = byLayer.size === 0 ? 0 : Math.max(...Array.from(byLayer.values()));
  return { depth, maxWidth };
}

/** Tarjan SCC — returns components in reverse finishing order (each SCC contiguous). */
function tarjanStronglyConnectedComponents(
  vertexIds: string[],
  adj: Map<string, string[]>
): string[][] {
  const ids = [...vertexIds];
  let index = 0;
  const stack: string[] = [];
  const onStack = new Set<string>();
  const indices = new Map<string, number>();
  const lowlink = new Map<string, number>();
  const sccs: string[][] = [];

  function strongConnect(v: string): void {
    indices.set(v, index);
    lowlink.set(v, index);
    index += 1;
    stack.push(v);
    onStack.add(v);

    for (const w of adj.get(v) ?? []) {
      if (!indices.has(w)) {
        strongConnect(w);
        lowlink.set(v, Math.min(lowlink.get(v)!, lowlink.get(w)!));
      } else if (onStack.has(w)) {
        lowlink.set(v, Math.min(lowlink.get(v)!, indices.get(w)!));
      }
    }

    if (lowlink.get(v) === indices.get(v)) {
      const comp: string[] = [];
      while (stack.length > 0) {
        const w = stack.pop()!;
        onStack.delete(w);
        comp.push(w);
        if (w === v) break;
      }
      sccs.push(comp);
    }
  }

  for (const v of ids) {
    if (!indices.has(v)) strongConnect(v);
  }

  return sccs;
}

function countWeaklyConnectedComponents(vertexIds: string[], edges: Array<{ source: string; target: string }>): number {
  const adj = new Map<string, Set<string>>();
  for (const id of vertexIds) adj.set(id, new Set());
  for (const e of edges) {
    adj.get(e.source)?.add(e.target);
    adj.get(e.target)?.add(e.source);
  }
  const visited = new Set<string>();
  let count = 0;
  for (const id of vertexIds) {
    if (visited.has(id)) continue;
    count++;
    const stack = [id];
    visited.add(id);
    while (stack.length) {
      const v = stack.pop()!;
      for (const n of adj.get(v) ?? []) {
        if (!visited.has(n)) {
          visited.add(n);
          stack.push(n);
        }
      }
    }
  }
  return count;
}

export function remapStudioCanvasLayoutVertices(
  nodes: Node[],
  edges: Edge[]
): {
  vertexIds: string[];
  directedEdges: Array<{ source: string; target: string }>;
} {
  const groupNodes = nodes.filter((n) => n.type === 'groupNode');
  const classNodes = nodes.filter((n) => n.type !== 'groupNode');
  const nodeToGroup = new Map<string, string>();
  for (const g of groupNodes) {
    const memberIds = (g.data as { nodeIds?: string[] })?.nodeIds ?? [];
    for (const id of memberIds) nodeToGroup.set(id, g.id);
  }

  const vertexSet = new Set<string>();
  for (const n of classNodes) {
    if (nodeToGroup.has(n.id)) continue;
    vertexSet.add(n.id);
  }
  for (const g of groupNodes) vertexSet.add(g.id);

  const remapEndpoint = (id: string): string | null => {
    if (vertexSet.has(id)) return id;
    const g = nodeToGroup.get(id);
    return g && vertexSet.has(g) ? g : null;
  };

  const seen = new Set<string>();
  const directedEdges: Array<{ source: string; target: string }> = [];

  for (const e of edges) {
    const s = remapEndpoint(e.source);
    const t = remapEndpoint(e.target);
    if (!s || !t || s === t) continue;
    const key = `${s}\0${t}`;
    if (seen.has(key)) continue;
    seen.add(key);
    directedEdges.push({ source: s, target: t });
  }

  return { vertexIds: [...vertexSet], directedEdges };
}

export function analyzeCanvasLayoutGraph(
  nodes: Node[],
  edges: Edge[],
  options?: { deepestDependencyChainLength?: number | null }
): CanvasLayoutGraphAnalysis | null {
  const classNodes = nodes.filter((n) => n.type !== 'groupNode');
  if (classNodes.length === 0) return null;

  const { vertexIds, directedEdges } = remapStudioCanvasLayoutVertices(nodes, edges);
  if (vertexIds.length === 0) return null;
  const vertexLabels = buildVertexLabelMap(nodes);

  const adjacency = buildAdjacencyMaps(directedEdges);
  const adjacencyMap = new Map<string, string[]>();
  for (const id of vertexIds) {
    adjacencyMap.set(id, adjacency.outgoing.get(id) ?? []);
  }

  const inDeg = new Map<string, number>();
  const outDeg = new Map<string, number>();
  for (const id of vertexIds) {
    inDeg.set(id, (adjacency.incoming.get(id) ?? []).length);
    outDeg.set(id, (adjacency.outgoing.get(id) ?? []).length);
  }

  const hubs: CanvasLayoutHubEntry[] = vertexIds
    .map((id) => {
      const inc = inDeg.get(id) ?? 0;
      const out = outDeg.get(id) ?? 0;
      return {
        id,
        name: getVertexLabel(vertexLabels, id),
        inDegree: inc,
        outDegree: out,
        totalDegree: inc + out,
      };
    })
    .sort((a, b) => b.totalDegree - a.totalDegree || compareLabels(a.name, b.name))
    .slice(0, 12);

  const roots: CanvasLayoutRootEntry[] = vertexIds
    .filter((id) => (inDeg.get(id) ?? 0) === 0)
    .map((id) => ({ id, name: getVertexLabel(vertexLabels, id) }))
    .sort((a, b) => compareLabels(a.name, b.name));

  const rawSccs = tarjanStronglyConnectedComponents(vertexIds, adjacencyMap);
  const sccEntries: CanvasLayoutSccEntry[] = rawSccs
    .map((memberIds) => ({
      memberIds: [...memberIds].sort(),
      memberNames: [...memberIds].map((id) => getVertexLabel(vertexLabels, id)).sort(compareLabels),
    }))
    .sort((a, b) => b.memberIds.length - a.memberIds.length);

  const nonTrivialSccCount = sccEntries.filter((s) => s.memberIds.length > 1).length;

  const layerAssignments = assignPseudoLayers(vertexIds, adjacency);
  const { depth: pseudoLayerDepth, maxWidth: pseudoLayerMaxWidth } = layerDepthAndMaxWidth(layerAssignments);

  const schemaDepth = options?.deepestDependencyChainLength;
  const hasSchemaDepth = typeof schemaDepth === 'number' && schemaDepth > 0;

  let recommendedDirection: 'TB' | 'LR' = 'TB';
  let recommendationReason =
    'Top-to-bottom fits typical dependency flow and matches the default hierarchical auto-layout.';

  if (directedEdges.length === 0) {
    recommendationReason = 'No canvas edges — either stack (TB) or arrange in a row (LR); TB is the default.';
  } else if (nonTrivialSccCount > 0) {
    recommendedDirection = 'LR';
    recommendationReason =
      'Directed cycles detected (strongly connected components). A left-to-right flow often separates cyclic clusters more readably than a strict vertical stack.';
  } else if (hasSchemaDepth && schemaDepth >= 5 && pseudoLayerMaxWidth <= pseudoLayerDepth + 2) {
    recommendedDirection = 'TB';
    recommendationReason = `Long dependency chains (${schemaDepth} steps in the schema graph) favor top-to-bottom layering.`;
  } else if (pseudoLayerMaxWidth > pseudoLayerDepth + 1 && pseudoLayerMaxWidth >= 4) {
    recommendedDirection = 'LR';
    recommendationReason =
      'Wide layers (many siblings at once) often read better left-to-right so parallel branches do not crowd vertically.';
  } else if (pseudoLayerDepth > pseudoLayerMaxWidth + 1 && pseudoLayerDepth >= 4) {
    recommendedDirection = 'TB';
    recommendationReason = 'Deep layering from canvas edges suggests top-to-bottom hierarchical layout.';
  }

  const weaklyConnectedComponentCount = countWeaklyConnectedComponents(vertexIds, directedEdges);

  return {
    classCount: classNodes.length,
    edgeCount: edges.length,
    vertexCount: vertexIds.length,
    recommendedDirection,
    recommendationReason,
    stronglyConnectedComponents: sccEntries,
    nonTrivialSccCount,
    hubClasses: hubs,
    hierarchyRoots: roots,
    weaklyConnectedComponentCount,
    pseudoLayerDepth,
    pseudoLayerMaxWidth,
  };
}

/** Stable digest for Ollama cache keys and request bodies. */
export function canvasLayoutAnalysisDigest(analysis: CanvasLayoutGraphAnalysis): string {
  return stableStringify(analysis);
}
