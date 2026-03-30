/**
 * Nested canvas groups (#155): hierarchy helpers, depth limits, subtree collection.
 */

import type { CanvasGroup } from '@/app/ade/studio/StudioContext';
export { sortGroupsParentsBeforeChildren } from '@lib/utils/group-sort';

/** Allowed group depths: level 1 (root) … level 3 (deepest). */
export const MAX_CANVAS_GROUP_DEPTH = 3;

export function groupById(groups: CanvasGroup[]): Map<string, CanvasGroup> {
  return new Map(groups.map((g) => [g.id, g]));
}

/** Depth 1 = top-level (no parent). Safe against cycles via a visited set. */
export function getGroupDepth(groupId: string, byId: Map<string, CanvasGroup>): number {
  let depth = 1;
  let cur = byId.get(groupId);
  const visited = new Set<string>();
  visited.add(groupId);
  while (cur?.parentId) {
    if (visited.has(cur.parentId)) break; // cycle guard
    visited.add(cur.parentId);
    depth += 1;
    cur = byId.get(cur.parentId);
  }
  return depth;
}

/** Longest chain of child groups strictly below `groupId` (edge count to deepest descendant group). Safe against cycles via a visited set. */
export function maxChildGroupChainLength(groupId: string, groups: CanvasGroup[], _visited: Set<string> = new Set()): number {
  if (_visited.has(groupId)) return 0; // cycle guard
  _visited.add(groupId);
  let maxBelow = 0;
  for (const g of groups) {
    if (g.parentId === groupId) {
      maxBelow = Math.max(maxBelow, 1 + maxChildGroupChainLength(g.id, groups, _visited));
    }
  }
  return maxBelow;
}

/**
 * After move, deepest group depth in this subtree would be:
 * newDepth(moved) + maxChildGroupChainLength(moved).
 */
export function wouldNestExceedMaxDepth(
  movingGroupId: string,
  newParentId: string | null | undefined,
  groups: CanvasGroup[],
  maxDepth: number = MAX_CANVAS_GROUP_DEPTH
): boolean {
  const byId = groupById(groups);
  const baseDepth = newParentId ? getGroupDepth(newParentId, byId) + 1 : 1;
  const tail = maxChildGroupChainLength(movingGroupId, groups);
  return baseDepth + tail > maxDepth;
}

/** True if `maybeDescendantId` is a strict descendant group of `ancestorId` (walks parent chain from the former). Safe against cycles via a visited set. */
export function isStrictDescendantGroup(
  ancestorId: string,
  maybeDescendantId: string,
  byId: Map<string, CanvasGroup>
): boolean {
  let cur = byId.get(maybeDescendantId);
  const visited = new Set<string>();
  visited.add(maybeDescendantId);
  while (cur?.parentId) {
    if (cur.parentId === ancestorId) return true;
    if (visited.has(cur.parentId)) break; // cycle guard
    visited.add(cur.parentId);
    cur = byId.get(cur.parentId);
  }
  return false;
}

/** All strict descendant group ids (not including rootId). */
export function collectDescendantGroupIds(rootId: string, groups: CanvasGroup[]): Set<string> {
  const out = new Set<string>();
  const visit = (id: string) => {
    for (const g of groups) {
      if (g.parentId === id && !out.has(g.id)) {
        out.add(g.id);
        visit(g.id);
      }
    }
  };
  visit(rootId);
  return out;
}

/** Subtree: root + all descendant groups. */
export function collectSubtreeGroupIds(rootId: string, groups: CanvasGroup[]): Set<string> {
  const desc = collectDescendantGroupIds(rootId, groups);
  desc.add(rootId);
  return desc;
}

/** Every class id assigned to this group or a descendant group (deduped). */
export function collectAllNodeIdsInGroupSubtree(groupId: string, groups: CanvasGroup[]): string[] {
  const ids = collectSubtreeGroupIds(groupId, groups);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const g of groups) {
    if (!ids.has(g.id)) continue;
    for (const nid of g.nodeIds || []) {
      if (!seen.has(nid)) {
        seen.add(nid);
        out.push(nid);
      }
    }
  }
  return out;
}

export type FlowLikeGroupNode = {
  id: string;
  type?: string;
  position: { x: number; y: number };
  measured?: { width?: number; height?: number };
  width?: number | string;
  height?: number | string;
  style?: { width?: number | string; height?: number | string };
};

function numDim(v: number | string | undefined, fallback: number): number {
  if (v === undefined) return fallback;
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  const n = typeof v === 'string' ? parseFloat(v) : NaN;
  return Number.isFinite(n) ? n : fallback;
}

export function getGroupNodeBounds(node: FlowLikeGroupNode): {
  x: number;
  y: number;
  width: number;
  height: number;
  area: number;
} {
  const width = numDim(node.measured?.width ?? node.width ?? node.style?.width, 400);
  const height = numDim(node.measured?.height ?? node.height ?? node.style?.height, 300);
  return { x: node.position.x, y: node.position.y, width, height, area: width * height };
}

/**
 * Among group frames whose bounds contain (x,y), return the id of the smallest area
 * (innermost when frames overlap). Excludes `excludeIds`.
 */
export function findInnermostGroupAtPosition(
  x: number,
  y: number,
  groupFlowNodes: ReadonlyArray<FlowLikeGroupNode>,
  excludeIds: Set<string>
): string | null {
  let best: { id: string; area: number } | null = null;
  for (const n of groupFlowNodes) {
    if (n.type !== 'groupNode' || excludeIds.has(n.id)) continue;
    const b = getGroupNodeBounds(n);
    const inside = x >= b.x && x <= b.x + b.width && y >= b.y && y <= b.y + b.height;
    if (!inside) continue;
    if (!best || b.area < best.area) {
      best = { id: n.id, area: b.area };
    }
  }
  return best?.id ?? null;
}
