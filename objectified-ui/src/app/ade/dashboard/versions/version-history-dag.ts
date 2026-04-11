/**
 * Revision history DAG for ADE Versions (#743, #744).
 * Builds a subgraph from parent_version_id + merge_parent_version_id with windowing.
 * #744: left-to-right layered layout (lanes), branch tips vs merge styling, branch filtering.
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

/** Named branch metadata from `/version-branches` — used for tips, labels, and filtering (#744). */
export type VersionHistoryBranchMeta = {
  id: string;
  name: string;
  tip_version_id: string;
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

/**
 * When the user narrows which named branches to include, keep the union of all
 * ancestors of each selected branch tip (following primary and merge parents)
 * so merge commits stay connected and readable.
 */
export function filterVersionsBySelectedBranches(
  all: VersionHistoryVertex[],
  branches: VersionHistoryBranchMeta[],
  selectedBranchIds: string[]
): VersionHistoryVertex[] {
  if (all.length === 0) return [];
  if (branches.length === 0) return all;
  if (selectedBranchIds.length === 0) return [];
  if (selectedBranchIds.length >= branches.length) return all;

  const byId = new Map(all.map((v) => [v.id, v]));
  const selected = new Set(selectedBranchIds);
  const allowed = new Set<string>();

  const walk = (vid: string) => {
    if (!byId.has(vid) || allowed.has(vid)) return;
    allowed.add(vid);
    const v = byId.get(vid)!;
    const p = v.parent_version_id?.trim();
    const m = v.merge_parent_version_id?.trim();
    if (p) walk(p);
    if (m) walk(m);
  };

  for (const b of branches) {
    if (!selected.has(b.id)) continue;
    const tip = b.tip_version_id?.trim();
    if (tip) walk(tip);
  }

  return all.filter((v) => allowed.has(v.id));
}

function branchNamesByTipVersionId(branches: VersionHistoryBranchMeta[]): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const b of branches) {
    const tid = b.tip_version_id?.trim();
    if (!tid) continue;
    const list = m.get(tid) ?? [];
    list.push(b.name);
    m.set(tid, list);
  }
  return m;
}

const TIP_ACCENT_BORDER = [
  'border-l-emerald-500',
  'border-l-sky-500',
  'border-l-amber-500',
  'border-l-rose-500',
  'border-l-cyan-500',
  'border-l-orange-500',
  'border-l-teal-500',
  'border-l-indigo-500',
] as const;

export function tipAccentClassForBranchNames(names: string[]): string {
  if (names.length === 0) return '';
  const s = [...names].sort().join('\0');
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  const idx = Math.abs(h) % TIP_ACCENT_BORDER.length;
  return TIP_ACCENT_BORDER[idx];
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
        style: { strokeWidth: 2, stroke: 'rgb(100 116 139)' },
      });
    }
    const m = v.merge_parent_version_id?.trim();
    if (m && ids.has(m)) {
      edges.push({
        id: `hist-m-${seq++}`,
        source: m,
        target: v.id,
        type: 'smoothstep',
        style: { strokeWidth: 2, strokeDasharray: '6 4', stroke: 'rgb(139 92 246)' },
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
  /** True when this revision is the tip of at least one named branch (#744). */
  isBranchTip: boolean;
  /** Branch names whose tip is this revision — used for labels and hover (#744). */
  branchNamesForTip: string[];
  tipAccentClass: string;
  layoutDirection: 'LR';
  shortMessage?: string | null;
};

export type BuildLayoutedHistoryGraphOptions = {
  branches?: VersionHistoryBranchMeta[];
};

export function buildLayoutedHistoryGraph(
  versions: VersionHistoryVertex[],
  _options?: BuildLayoutedHistoryGraphOptions
): {
  nodes: Node<RevisionNodeData>[];
  edges: Edge[];
} {
  if (versions.length === 0) {
    return { nodes: [], edges: [] };
  }
  const branches = _options?.branches ?? [];
  const tips = branchNamesByTipVersionId(branches);

  const edges = buildHistoryEdges(versions);
  const rfNodes: Node<RevisionNodeData>[] = versions.map((v) => {
    const isMerge = !!(v.merge_parent_version_id && v.merge_parent_version_id.trim());
    const branchNamesForTip = tips.get(v.id) ?? [];
    const isBranchTip = branchNamesForTip.length > 0;
    const tipAccentClass = tipAccentClassForBranchNames(branchNamesForTip);
    return {
      id: v.id,
      type: 'revisionHistory',
      position: { x: 0, y: 0 },
      data: {
        versionString: v.version_id,
        isMerge,
        isBranchTip,
        branchNamesForTip,
        tipAccentClass,
        layoutDirection: 'LR',
        shortMessage: v.shortMessage ?? null,
      },
      width: NODE_W,
      height: NODE_H,
      measured: { width: NODE_W, height: NODE_H },
    };
  });

  const laidOut = applyAutoLayout(rfNodes, edges, {
    direction: 'LR',
    nodeSpacingX: 56,
    nodeSpacingY: 64,
    padding: 36,
    centerNodes: true,
    minimizeCrossings: true,
  });

  return { nodes: laidOut as Node<RevisionNodeData>[], edges };
}
