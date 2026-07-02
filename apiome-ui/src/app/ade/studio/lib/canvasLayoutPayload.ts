import type { Edge, Node } from '@xyflow/react';

/**
 * Serialize React Flow nodes for default/named canvas layout persistence.
 * Kept in one place for manual save and auto-save (#315).
 */
export function mapNodesForLayoutSave(nodes: Node[]) {
  return nodes.map((node) => ({
    id: node.id,
    type: node.type,
    position: node.position,
    dimensions: {
      width: node.measured?.width || node.width || node.style?.width,
      height: node.measured?.height || node.height || node.style?.height,
    },
    data:
      node.type === 'groupNode'
        ? {
            name: node.data.name,
            color: node.data.color,
            nodeIds: node.data.nodeIds,
            parentId: (node.data as { parentId?: string | null }).parentId ?? null,
          }
        : undefined,
  }));
}

/**
 * Serialize edges for canvas layout persistence.
 */
export function mapEdgesForLayoutSave(edges: Edge[]) {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
  }));
}
