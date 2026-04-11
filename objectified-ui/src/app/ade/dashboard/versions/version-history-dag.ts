/**
 * Revision history DAG for ADE Versions (#743).
 * Builds a subgraph from parent_version_id + merge_parent_version_id with windowing.
 */

import type { Edge, Node } from '@xyflow/react';
import { applyAutoLayout } from '@/app/utils/canvas-auto-layout';

export type VersionHistoryVertex = {
  id: string;
  version_id: string;
  parent_version_id?: string | null;
  merge_parent_version_id?: string | null;
  created_at?: string;
  shortMessage?: string | null;
};

export const DEFAULT_HISTORY_WINDOW = 60;
export const HISTORY_WINDOW_STEP = 40;
export const MAX_HISTORY_GRAPH_NODES = 400;

function parseTime(created_at?: string): number {
  if (!created_at) return 0;
  const t = new Date(created_at).getTime();
  return Number.isFinite(t) ? t : 0;
}

/**
 * Start from the N newest revisions (by created_at), then walk backward along
 * primary and merge parents so edges stay connected within the loaded set.
 */
export function expandVersionsForWindow(
  all: VersionHistoryVertex[],
  windowSize: number,
  maxTotal = MAX_HISTORY_GRAPH_NODES
): VersionHistoryVertex[] {
  if (all.length === 0) return [];
  const byId = new Map(all.map((v) => [v.id, v]));
  const sorted = [...all].sort((a, b) => parseTime(b.created_at) - parseTime(a.created_at));
  const cap = Math.max(1, Math.min(windowSize, sorted.length, maxTotal));
  const seeds = sorted.slice(0, cap);
  const out = new Map<string, VersionHistoryVertex>();
  const queue: VersionHistoryVertex[] = [];

  for (const s of seeds) {
    if (!out.has(s.id)) {
      out.set(s.id, s);
      queue.push(s);
    }
  }

  while (queue.length > 0 && out.size < maxTotal) {
    const v = queue.shift()!;
    const parents = [v.parent_version_id, v.merge_parent_version_id].filter(
      (x): x is string => typeof x === 'string' && x.trim().length > 0
    );
    for (const pid of parents) {
      if (out.has(pid)) continue;
      const p = byId.get(pid);
      if (!p) continue;
      out.set(pid, p);
      queue.push(p);
    }
  }

  return Array.from(out.values());
}

export function buildHistoryEdges(versions: VersionHistoryVertex[]): Edge[] {
  const ids = new Set(versions.map((v) => v.id));
  const edges: Edge[] = [];
  let seq = 0;
  for (const v of versions) {
    const p = v.parent_version_id?.trim();
    if (p && ids.has(p)) {
      edges.push({
        id: `hist-p-${seq++}`,
        source: p,
        target: v.id,
        type: 'smoothstep',
        style: { strokeWidth: 2 },
      });
    }
    const m = v.merge_parent_version_id?.trim();
    if (m && ids.has(m)) {
      edges.push({
        id: `hist-m-${seq++}`,
        source: m,
        target: v.id,
        type: 'smoothstep',
        style: { strokeWidth: 2, strokeDasharray: '6 4' },
      });
    }
  }
  return edges;
}

const NODE_W = 200;
const NODE_H = 52;

export type RevisionNodeData = {
  versionString: string;
  isMerge: boolean;
  shortMessage?: string | null;
};

export function buildLayoutedHistoryGraph(versions: VersionHistoryVertex[]): {
  nodes: Node<RevisionNodeData>[];
  edges: Edge[];
} {
  if (versions.length === 0) {
    return { nodes: [], edges: [] };
  }
  const edges = buildHistoryEdges(versions);
  const rfNodes: Node<RevisionNodeData>[] = versions.map((v) => {
    const isMerge = !!(v.merge_parent_version_id && v.merge_parent_version_id.trim());
    return {
      id: v.id,
      type: 'revisionHistory',
      position: { x: 0, y: 0 },
      data: {
        versionString: v.version_id,
        isMerge,
        shortMessage: v.shortMessage ?? null,
      },
      width: NODE_W,
      height: NODE_H,
      measured: { width: NODE_W, height: NODE_H },
    };
  });

  const laidOut = applyAutoLayout(rfNodes, edges, {
    direction: 'TB',
    nodeSpacingX: 48,
    nodeSpacingY: 72,
    padding: 32,
    centerNodes: true,
    minimizeCrossings: true,
  });

  return { nodes: laidOut as Node<RevisionNodeData>[], edges };
}
