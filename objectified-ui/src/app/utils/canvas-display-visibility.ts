/**
 * Canvas display visibility (#483): which class nodes remain visible after hide criteria.
 */

import type { CanvasGroupForVisibility } from '@/app/utils/canvas-node-visibility';

export interface CanvasClassNodeShape {
  id: string;
  type?: string;
  data?: {
    properties?: unknown[] | null;
    schema?: { deprecated?: boolean } | null;
  };
}

export interface CanvasHideCriteriaInput {
  hideEmptyClasses: boolean;
  /** When true, hide class nodes that have no incident edges (same as "Connected" view filter). */
  hideUnconnectedClasses: boolean;
  hideDeprecatedClasses: boolean;
  /** Group IDs whose member class nodes should be hidden. */
  hiddenGroupIds: Set<string>;
}

/** Class node IDs that should still appear on the canvas (before per-node manual hide). */
export function computeClassIdsPassingHideCriteria(
  classNodes: CanvasClassNodeShape[],
  groups: CanvasGroupForVisibility[],
  connectedNodeIds: Set<string>,
  criteria: CanvasHideCriteriaInput
): Set<string> {
  const inHiddenGroups = new Set<string>();
  for (const g of groups) {
    if (criteria.hiddenGroupIds.has(g.id)) {
      for (const id of g.nodeIds) {
        inHiddenGroups.add(id);
      }
    }
  }

  const visible = new Set<string>();
  for (const node of classNodes) {
    if (node.type === 'groupNode') continue;
    const props = node.data?.properties;
    const propCount = Array.isArray(props) ? props.length : 0;
    if (criteria.hideEmptyClasses && propCount === 0) continue;
    if (criteria.hideUnconnectedClasses && !connectedNodeIds.has(node.id)) continue;
    if (criteria.hideDeprecatedClasses && node.data?.schema?.deprecated === true) continue;
    if (inHiddenGroups.has(node.id)) continue;
    visible.add(node.id);
  }
  return visible;
}

/** Group frame is visible if at least one member class passes criteria. */
export function groupNodeIdIsVisible(
  group: CanvasGroupForVisibility,
  visibleClassIds: Set<string>
): boolean {
  return group.nodeIds.some((id) => visibleClassIds.has(id));
}
