import type { Node } from '@xyflow/react';

export interface AlignmentGuidesState {
  horizontal: Array<{ y: number; x1: number; x2: number }>;
  vertical: Array<{ x: number; y1: number; y2: number }>;
}

const SNAP_THRESHOLD = 8;

/**
 * Alignment guides for node drag (shared math with Designer editor/page.tsx — #2641).
 * If Designer drag logic changes, update this function and the cross-reference in editor.
 */
export function computeAlignmentGuidesForNode(
  node: Node,
  otherNodes: Node[],
  options?: { defaultWidth?: number; defaultHeight?: number; excludeTypes?: string[] }
): AlignmentGuidesState {
  const defaultWidth = options?.defaultWidth ?? 260;
  const defaultHeight = options?.defaultHeight ?? 200;
  const excludeTypes = new Set(options?.excludeTypes ?? []);

  const nodeWidth = (node.measured?.width as number) || (node.width as number) || defaultWidth;
  const nodeHeight = (node.measured?.height as number) || (node.height as number) || defaultHeight;
  const nodeCenterX = node.position.x + nodeWidth / 2;
  const nodeCenterY = node.position.y + nodeHeight / 2;
  const nodeLeft = node.position.x;
  const nodeRight = node.position.x + nodeWidth;
  const nodeTop = node.position.y;
  const nodeBottom = node.position.y + nodeHeight;

  const newHorizontalGuides: AlignmentGuidesState['horizontal'] = [];
  const newVerticalGuides: AlignmentGuidesState['vertical'] = [];

  const filtered = otherNodes.filter(
    (n) => n.id !== node.id && !excludeTypes.has(String(n.type ?? ''))
  );

  filtered.forEach((otherNode) => {
    const otherWidth =
      (otherNode.measured?.width as number) || (otherNode.width as number) || defaultWidth;
    const otherHeight =
      (otherNode.measured?.height as number) || (otherNode.height as number) || defaultHeight;
    const otherCenterX = otherNode.position.x + otherWidth / 2;
    const otherCenterY = otherNode.position.y + otherHeight / 2;
    const otherLeft = otherNode.position.x;
    const otherRight = otherNode.position.x + otherWidth;
    const otherTop = otherNode.position.y;
    const otherBottom = otherNode.position.y + otherHeight;

    const minX = Math.min(nodeLeft, otherLeft) - 20;
    const maxX = Math.max(nodeRight, otherRight) + 20;

    const minY = Math.min(nodeTop, otherTop) - 20;
    const maxY = Math.max(nodeBottom, otherBottom) + 20;

    if (Math.abs(nodeTop - otherTop) < SNAP_THRESHOLD) {
      newHorizontalGuides.push({ y: otherTop, x1: minX, x2: maxX });
    }
    if (Math.abs(nodeBottom - otherBottom) < SNAP_THRESHOLD) {
      newHorizontalGuides.push({ y: otherBottom, x1: minX, x2: maxX });
    }
    if (Math.abs(nodeCenterY - otherCenterY) < SNAP_THRESHOLD) {
      newHorizontalGuides.push({ y: otherCenterY, x1: minX, x2: maxX });
    }
    if (Math.abs(nodeTop - otherBottom) < SNAP_THRESHOLD) {
      newHorizontalGuides.push({ y: otherBottom, x1: minX, x2: maxX });
    }
    if (Math.abs(nodeBottom - otherTop) < SNAP_THRESHOLD) {
      newHorizontalGuides.push({ y: otherTop, x1: minX, x2: maxX });
    }

    if (Math.abs(nodeLeft - otherLeft) < SNAP_THRESHOLD) {
      newVerticalGuides.push({ x: otherLeft, y1: minY, y2: maxY });
    }
    if (Math.abs(nodeRight - otherRight) < SNAP_THRESHOLD) {
      newVerticalGuides.push({ x: otherRight, y1: minY, y2: maxY });
    }
    if (Math.abs(nodeCenterX - otherCenterX) < SNAP_THRESHOLD) {
      newVerticalGuides.push({ x: otherCenterX, y1: minY, y2: maxY });
    }
    if (Math.abs(nodeLeft - otherRight) < SNAP_THRESHOLD) {
      newVerticalGuides.push({ x: otherRight, y1: minY, y2: maxY });
    }
    if (Math.abs(nodeRight - otherLeft) < SNAP_THRESHOLD) {
      newVerticalGuides.push({ x: otherLeft, y1: minY, y2: maxY });
    }
  });

  return { horizontal: newHorizontalGuides, vertical: newVerticalGuides };
}
