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
  /** Full commit body — shown in the node hover tooltip when present (#745 polish). */
  commitMessage?: string | null;
  /** Author display name for the tooltip + node footer (#745 polish). */
  authorName?: string | null;
  /** Optional author user id; lets callers map to an avatar / profile link later. */
  creatorId?: string | null;
  /** Optional external reference (e.g. "JIRA-123") surfaced in the tooltip. */
  externalRef?: string | null;
};

/** Named branch metadata from `/version-branches` — used for tips, labels, and filtering (#744). */
export type VersionHistoryBranchMeta = {
  id: string;
  name: string;
  tip_version_id: string;
};

/** Minimal tag shape consumed by the graph for tag pill rendering. */
export type VersionHistoryTag = {
  id: string;
  name: string;
  version_id: string;
  immutable?: boolean;
  protected?: boolean;
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

export type LaneColor = {
  dot: string;
  ring: string;
  text: string;
};

/**
 * Lane palette for the commit dot and the lane legend. Kept parallel to `TIP_ACCENT_BORDER`
 * so a branch's accent border and its lane dot visually agree.
 */
export const LANE_COLOR_PALETTE: readonly LaneColor[] = [
  { dot: 'bg-emerald-500', ring: 'ring-emerald-500', text: 'text-emerald-700 dark:text-emerald-300' },
  { dot: 'bg-sky-500', ring: 'ring-sky-500', text: 'text-sky-700 dark:text-sky-300' },
  { dot: 'bg-amber-500', ring: 'ring-amber-500', text: 'text-amber-700 dark:text-amber-300' },
  { dot: 'bg-rose-500', ring: 'ring-rose-500', text: 'text-rose-700 dark:text-rose-300' },
  { dot: 'bg-cyan-500', ring: 'ring-cyan-500', text: 'text-cyan-700 dark:text-cyan-300' },
  { dot: 'bg-orange-500', ring: 'ring-orange-500', text: 'text-orange-700 dark:text-orange-300' },
  { dot: 'bg-teal-500', ring: 'ring-teal-500', text: 'text-teal-700 dark:text-teal-300' },
  { dot: 'bg-indigo-500', ring: 'ring-indigo-500', text: 'text-indigo-700 dark:text-indigo-300' },
];

const NEUTRAL_LANE: LaneColor = {
  dot: 'bg-slate-400',
  ring: 'ring-slate-400',
  text: 'text-slate-600 dark:text-slate-300',
};

export function tipAccentClassForBranchNames(names: string[]): string {
  if (names.length === 0) return '';
  const s = [...names].sort().join('\0');
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  const idx = Math.abs(h) % TIP_ACCENT_BORDER.length;
  return TIP_ACCENT_BORDER[idx];
}

export function laneColorForBranchIndex(index: number | null | undefined): LaneColor {
  if (index == null || index < 0) return NEUTRAL_LANE;
  return LANE_COLOR_PALETTE[index % LANE_COLOR_PALETTE.length];
}

/**
 * Assign each revision to the first named branch whose tip it is reachable from
 * (walking primary + merge parents). Revisions not reachable from any tip get no lane.
 * Branches are iterated in input order so the dashboard's chip ordering is stable.
 *
 * Returns maps keyed by `versionId`:
 *   - `laneIndex`: 0-based index into `branches` (lane palette index).
 *   - `laneBranchId`: id of the owning branch (useful for legend interactions).
 */
export function computeRevisionLanes(
  versions: VersionHistoryVertex[],
  branches: VersionHistoryBranchMeta[]
): {
  laneIndex: Map<string, number>;
  laneBranchId: Map<string, string>;
} {
  const laneIndex = new Map<string, number>();
  const laneBranchId = new Map<string, string>();
  if (versions.length === 0 || branches.length === 0) return { laneIndex, laneBranchId };

  const byId = new Map(versions.map((v) => [v.id, v]));

  branches.forEach((branch, idx) => {
    const tip = branch.tip_version_id?.trim();
    if (!tip || !byId.has(tip)) return;
    const stack = [tip];
    while (stack.length > 0) {
      const vid = stack.pop()!;
      if (laneIndex.has(vid)) continue;
      const v = byId.get(vid);
      if (!v) continue;
      laneIndex.set(vid, idx);
      laneBranchId.set(vid, branch.id);
      const p = v.parent_version_id?.trim();
      const m = v.merge_parent_version_id?.trim();
      if (p) stack.push(p);
      if (m) stack.push(m);
    }
  });

  return { laneIndex, laneBranchId };
}

/**
 * Compact "N minutes ago" style relative time — deliberately avoids a large i18n lib
 * since the node already shows the absolute ISO string in its title attribute.
 */
export function formatRelativeTime(iso?: string | null, now: number = Date.now()): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const diff = now - t;
  if (diff < 0) return 'just now';
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  const y = Math.floor(d / 365);
  return `${y}y ago`;
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
  /** Full commit message body for the tooltip. */
  fullMessage?: string | null;
  /** Author display name for the footer + tooltip. */
  authorName?: string | null;
  /** Relative time string (e.g. "2h ago") computed at layout time. */
  relativeTime?: string | null;
  /** Absolute ISO timestamp for the tooltip. */
  createdAt?: string | null;
  /** External ref (e.g. ticket id) surfaced in the tooltip. */
  externalRef?: string | null;
  /** Lane color for the commit dot; neutral slate when no lane assignment. */
  laneColor: LaneColor;
  /** 0-based lane index into the palette (null for unassigned). */
  laneIndex: number | null;
  /** Primary parent revision id — used to label the tooltip. */
  primaryParentId?: string | null;
  /** Merge parent revision id — used to label the tooltip for merge commits. */
  mergeParentId?: string | null;
  /** Tags pointing at this revision. */
  tags: VersionHistoryTag[];
  /** Branch actions exposed via the node's dropdown menu + right-click ContextMenu. */
  onBranchFromRevision?: (revisionId: string) => void;
  /** Canvas-only: switch the editor to this revision. When undefined the item is hidden. */
  onCheckoutRevision?: (revisionId: string) => void;
  /** Open read-only spec for this revision. */
  onViewSpec?: (revisionId: string) => void;
  /** Compare this revision with its primary parent. */
  onCompareToPrimaryParent?: (revisionId: string) => void;
};

export type BuildLayoutedHistoryGraphOptions = {
  branches?: VersionHistoryBranchMeta[];
  tags?: VersionHistoryTag[];
  onBranchFromRevision?: (revisionId: string) => void;
  onCheckoutRevision?: (revisionId: string) => void;
  onViewSpec?: (revisionId: string) => void;
  onCompareToPrimaryParent?: (revisionId: string) => void;
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
  const tagsInput = _options?.tags ?? [];
  const onBranchFromRevision = _options?.onBranchFromRevision;
  const onCheckoutRevision = _options?.onCheckoutRevision;
  const onViewSpec = _options?.onViewSpec;
  const onCompareToPrimaryParent = _options?.onCompareToPrimaryParent;
  const tips = branchNamesByTipVersionId(branches);
  const { laneIndex } = computeRevisionLanes(versions, branches);
  const now = Date.now();

  const tagsByVersion = new Map<string, VersionHistoryTag[]>();
  for (const t of tagsInput) {
    const list = tagsByVersion.get(t.version_id) ?? [];
    list.push(t);
    tagsByVersion.set(t.version_id, list);
  }

  const edges = buildHistoryEdges(versions);
  const rfNodes: Node<RevisionNodeData>[] = versions.map((v) => {
    const isMerge = !!(v.merge_parent_version_id && v.merge_parent_version_id.trim());
    const branchNamesForTip = tips.get(v.id) ?? [];
    const isBranchTip = branchNamesForTip.length > 0;
    const tipAccentClass = tipAccentClassForBranchNames(branchNamesForTip);
    const lane = laneIndex.get(v.id);
    const laneColor = laneColorForBranchIndex(lane);
    const tagsForVersion = tagsByVersion.get(v.version_id) ?? [];
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
        fullMessage: v.commitMessage ?? null,
        authorName: v.authorName ?? null,
        relativeTime: formatRelativeTime(v.created_at, now),
        createdAt: v.created_at ?? null,
        externalRef: v.externalRef ?? null,
        laneColor,
        laneIndex: lane ?? null,
        primaryParentId: v.parent_version_id ?? null,
        mergeParentId: v.merge_parent_version_id ?? null,
        tags: tagsForVersion,
        onBranchFromRevision,
        onCheckoutRevision,
        onViewSpec,
        onCompareToPrimaryParent,
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
