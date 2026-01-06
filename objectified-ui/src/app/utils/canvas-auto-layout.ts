/**
 * Canvas Auto-Layout Algorithm
 *
 * Implements a layered/hierarchical layout algorithm (Sugiyama-style) for
 * automatically arranging class nodes on the canvas. This layout is optimized
 * for dependency graphs and produces clean orthogonal edge routing.
 */

import type { Node, Edge } from '@xyflow/react';

/**
 * Layout configuration options
 */
export interface AutoLayoutOptions {
  /** Horizontal spacing between nodes in the same layer */
  nodeSpacingX: number;
  /** Vertical spacing between layers */
  nodeSpacingY: number;
  /** Direction of the layout */
  direction: 'TB' | 'BT' | 'LR' | 'RL';
  /** Padding around the entire layout */
  padding: number;
  /** Whether to center nodes within their layer */
  centerNodes: boolean;
  /** Whether to minimize edge crossings (more computation) */
  minimizeCrossings: boolean;
}

const DEFAULT_OPTIONS: AutoLayoutOptions = {
  nodeSpacingX: 80,
  nodeSpacingY: 120,
  direction: 'TB',
  padding: 50,
  centerNodes: true,
  minimizeCrossings: true,
};

/**
 * Node with additional layout information
 */
interface LayoutNode {
  id: string;
  layer: number;
  position: number;
  width: number;
  height: number;
  incomingEdges: string[];
  outgoingEdges: string[];
}

/**
 * Build an adjacency map from edges
 */
function buildAdjacencyMap(edges: Edge[]): {
  outgoing: Map<string, string[]>;
  incoming: Map<string, string[]>;
} {
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();

  edges.forEach(edge => {
    const sources = outgoing.get(edge.source) || [];
    sources.push(edge.target);
    outgoing.set(edge.source, sources);

    const targets = incoming.get(edge.target) || [];
    targets.push(edge.source);
    incoming.set(edge.target, targets);
  });

  return { outgoing, incoming };
}

/**
 * Assign layers to nodes using longest path algorithm
 * Nodes with no incoming edges are placed in layer 0
 */
function assignLayers(
  nodeIds: string[],
  adjacency: { outgoing: Map<string, string[]>; incoming: Map<string, string[]> }
): Map<string, number> {
  const layers = new Map<string, number>();
  const visited = new Set<string>();

  // Find root nodes (no incoming edges)
  const rootNodes = nodeIds.filter(id => {
    const incoming = adjacency.incoming.get(id) || [];
    return incoming.length === 0;
  });

  // If no root nodes, use nodes with minimum incoming edges
  if (rootNodes.length === 0) {
    // Find the node with minimum incoming edges to break cycles
    let minIncoming = Infinity;
    let minNode = nodeIds[0];
    nodeIds.forEach(id => {
      const incoming = adjacency.incoming.get(id) || [];
      if (incoming.length < minIncoming) {
        minIncoming = incoming.length;
        minNode = id;
      }
    });
    rootNodes.push(minNode);
  }

  // BFS to assign layers
  const queue: { id: string; layer: number }[] = rootNodes.map(id => ({ id, layer: 0 }));

  while (queue.length > 0) {
    const { id, layer } = queue.shift()!;

    if (visited.has(id)) {
      // Update layer if we found a longer path
      const existingLayer = layers.get(id) || 0;
      if (layer > existingLayer) {
        layers.set(id, layer);
      }
      continue;
    }

    visited.add(id);
    layers.set(id, layer);

    const outgoing = adjacency.outgoing.get(id) || [];
    outgoing.forEach(targetId => {
      queue.push({ id: targetId, layer: layer + 1 });
    });
  }

  // Handle disconnected nodes
  nodeIds.forEach(id => {
    if (!layers.has(id)) {
      layers.set(id, 0);
    }
  });

  return layers;
}

/**
 * Order nodes within each layer to minimize edge crossings
 * Uses barycenter heuristic
 */
function orderNodesInLayers(
  layerAssignments: Map<string, number>,
  adjacency: { outgoing: Map<string, string[]>; incoming: Map<string, string[]> },
  minimizeCrossings: boolean
): Map<number, string[]> {
  const layers = new Map<number, string[]>();

  // Group nodes by layer
  layerAssignments.forEach((layer, nodeId) => {
    const nodesInLayer = layers.get(layer) || [];
    nodesInLayer.push(nodeId);
    layers.set(layer, nodesInLayer);
  });

  if (!minimizeCrossings) {
    return layers;
  }

  // Get max layer
  const maxLayer = Math.max(...Array.from(layers.keys()));

  // Barycenter heuristic - multiple passes
  for (let iteration = 0; iteration < 4; iteration++) {
    // Forward pass
    for (let layer = 1; layer <= maxLayer; layer++) {
      const nodesInLayer = layers.get(layer) || [];
      const prevLayerNodes = layers.get(layer - 1) || [];

      // Calculate barycenter for each node
      const barycenters = nodesInLayer.map(nodeId => {
        const incoming = adjacency.incoming.get(nodeId) || [];
        const positions = incoming
          .filter(src => prevLayerNodes.includes(src))
          .map(src => prevLayerNodes.indexOf(src));

        if (positions.length === 0) return { nodeId, barycenter: Infinity };
        const barycenter = positions.reduce((a, b) => a + b, 0) / positions.length;
        return { nodeId, barycenter };
      });

      // Sort by barycenter
      barycenters.sort((a, b) => a.barycenter - b.barycenter);
      layers.set(layer, barycenters.map(b => b.nodeId));
    }

    // Backward pass
    for (let layer = maxLayer - 1; layer >= 0; layer--) {
      const nodesInLayer = layers.get(layer) || [];
      const nextLayerNodes = layers.get(layer + 1) || [];

      // Calculate barycenter for each node
      const barycenters = nodesInLayer.map(nodeId => {
        const outgoing = adjacency.outgoing.get(nodeId) || [];
        const positions = outgoing
          .filter(tgt => nextLayerNodes.includes(tgt))
          .map(tgt => nextLayerNodes.indexOf(tgt));

        if (positions.length === 0) return { nodeId, barycenter: Infinity };
        const barycenter = positions.reduce((a, b) => a + b, 0) / positions.length;
        return { nodeId, barycenter };
      });

      // Sort by barycenter
      barycenters.sort((a, b) => a.barycenter - b.barycenter);
      layers.set(layer, barycenters.map(b => b.nodeId));
    }
  }

  return layers;
}

/**
 * Calculate final positions for nodes
 */
function calculatePositions(
  orderedLayers: Map<number, string[]>,
  nodeDimensions: Map<string, { width: number; height: number }>,
  options: AutoLayoutOptions
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const isHorizontal = options.direction === 'LR' || options.direction === 'RL';
  const isReversed = options.direction === 'BT' || options.direction === 'RL';

  // Calculate max width/height for each layer
  const layerSizes = new Map<number, { maxWidth: number; maxHeight: number; totalWidth: number; totalHeight: number }>();

  orderedLayers.forEach((nodesInLayer, layer) => {
    let maxWidth = 0;
    let maxHeight = 0;
    let totalWidth = 0;
    let totalHeight = 0;

    nodesInLayer.forEach((nodeId, index) => {
      const dim = nodeDimensions.get(nodeId) || { width: 280, height: 100 };
      maxWidth = Math.max(maxWidth, dim.width);
      maxHeight = Math.max(maxHeight, dim.height);
      totalWidth += dim.width + (index > 0 ? options.nodeSpacingX : 0);
      totalHeight += dim.height + (index > 0 ? options.nodeSpacingY : 0);
    });

    layerSizes.set(layer, { maxWidth, maxHeight, totalWidth, totalHeight });
  });

  // Calculate layer offsets
  const layerOffsets = new Map<number, number>();
  let currentOffset = options.padding;

  const sortedLayers = Array.from(orderedLayers.keys()).sort((a, b) => a - b);

  sortedLayers.forEach((layer, index) => {
    if (isReversed) {
      layerOffsets.set(layer, currentOffset);
    } else {
      layerOffsets.set(layer, currentOffset);
    }

    const sizes = layerSizes.get(layer)!;
    if (isHorizontal) {
      currentOffset += sizes.maxWidth + options.nodeSpacingY;
    } else {
      currentOffset += sizes.maxHeight + options.nodeSpacingY;
    }
  });

  // Calculate positions within each layer
  orderedLayers.forEach((nodesInLayer, layer) => {
    const layerOffset = layerOffsets.get(layer) || 0;
    const sizes = layerSizes.get(layer)!;

    // Calculate total size of nodes in this layer
    const totalSize = nodesInLayer.reduce((sum, nodeId, index) => {
      const dim = nodeDimensions.get(nodeId) || { width: 280, height: 100 };
      const size = isHorizontal ? dim.height : dim.width;
      return sum + size + (index > 0 ? options.nodeSpacingX : 0);
    }, 0);

    // Calculate starting offset for centering
    let nodeOffset = options.padding;
    if (options.centerNodes) {
      // Center relative to the widest layer
      const maxTotalSize = Math.max(...Array.from(layerSizes.values()).map(s =>
        isHorizontal ? s.totalHeight : s.totalWidth
      ));
      nodeOffset = options.padding + (maxTotalSize - totalSize) / 2;
    }

    nodesInLayer.forEach((nodeId) => {
      const dim = nodeDimensions.get(nodeId) || { width: 280, height: 100 };

      let x: number, y: number;

      if (isHorizontal) {
        x = layerOffset;
        y = nodeOffset;
        nodeOffset += dim.height + options.nodeSpacingX;
      } else {
        x = nodeOffset;
        y = layerOffset;
        nodeOffset += dim.width + options.nodeSpacingX;
      }

      positions.set(nodeId, { x, y });
    });
  });

  return positions;
}

/**
 * Apply auto-layout to nodes
 * Returns new nodes array with updated positions
 */
export function applyAutoLayout(
  nodes: Node[],
  edges: Edge[],
  options: Partial<AutoLayoutOptions> = {}
): Node[] {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  // Filter out group nodes - only layout class nodes
  const classNodes = nodes.filter(n => n.type !== 'groupNode');
  const groupNodes = nodes.filter(n => n.type === 'groupNode');

  if (classNodes.length === 0) {
    return nodes;
  }

  // Build adjacency map
  const adjacency = buildAdjacencyMap(edges);

  // Get node IDs
  const nodeIds = classNodes.map(n => n.id);

  // Assign layers
  const layerAssignments = assignLayers(nodeIds, adjacency);

  // Order nodes within layers
  const orderedLayers = orderNodesInLayers(layerAssignments, adjacency, opts.minimizeCrossings);

  // Get node dimensions
  const nodeDimensions = new Map<string, { width: number; height: number }>();
  classNodes.forEach(node => {
    nodeDimensions.set(node.id, {
      width: node.measured?.width || (node.width as number) || 280,
      height: node.measured?.height || (node.height as number) || 100,
    });
  });

  // Calculate positions
  const positions = calculatePositions(orderedLayers, nodeDimensions, opts);

  // Apply positions to nodes
  const layoutedClassNodes = classNodes.map(node => ({
    ...node,
    position: positions.get(node.id) || node.position,
  }));

  // Return all nodes (class nodes with new positions + unchanged group nodes)
  return [...layoutedClassNodes, ...groupNodes];
}

/**
 * Create orthogonal edge path
 * Creates a path with only horizontal and vertical segments
 */
export function createOrthogonalEdgePath(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  sourcePosition: 'top' | 'bottom' | 'left' | 'right' = 'bottom',
  targetPosition: 'top' | 'bottom' | 'left' | 'right' = 'top'
): string {
  const midY = (sourceY + targetY) / 2;
  const midX = (sourceX + targetX) / 2;

  // Determine path based on positions
  if (sourcePosition === 'bottom' && targetPosition === 'top') {
    // Source below, target above - typical top-bottom layout
    if (sourceY < targetY) {
      // Source is actually above target
      return `M ${sourceX} ${sourceY} L ${sourceX} ${midY} L ${targetX} ${midY} L ${targetX} ${targetY}`;
    } else {
      return `M ${sourceX} ${sourceY} L ${sourceX} ${midY} L ${targetX} ${midY} L ${targetX} ${targetY}`;
    }
  }

  if (sourcePosition === 'right' && targetPosition === 'left') {
    // Left-right layout
    return `M ${sourceX} ${sourceY} L ${midX} ${sourceY} L ${midX} ${targetY} L ${targetX} ${targetY}`;
  }

  // Default orthogonal path
  return `M ${sourceX} ${sourceY} L ${sourceX} ${midY} L ${targetX} ${midY} L ${targetX} ${targetY}`;
}

/**
 * Fit the viewport to show all nodes after layout
 */
export function calculateFitViewport(
  nodes: Node[],
  viewportWidth: number,
  viewportHeight: number,
  padding: number = 50
): { x: number; y: number; zoom: number } {
  if (nodes.length === 0) {
    return { x: 0, y: 0, zoom: 1 };
  }

  // Calculate bounding box
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  nodes.forEach(node => {
    const width = node.measured?.width || (node.width as number) || 280;
    const height = node.measured?.height || (node.height as number) || 100;

    minX = Math.min(minX, node.position.x);
    minY = Math.min(minY, node.position.y);
    maxX = Math.max(maxX, node.position.x + width);
    maxY = Math.max(maxY, node.position.y + height);
  });

  // Add padding
  minX -= padding;
  minY -= padding;
  maxX += padding;
  maxY += padding;

  // Calculate zoom to fit
  const contentWidth = maxX - minX;
  const contentHeight = maxY - minY;

  const zoomX = viewportWidth / contentWidth;
  const zoomY = viewportHeight / contentHeight;
  const zoom = Math.min(zoomX, zoomY, 1); // Don't zoom in beyond 100%

  // Calculate center position
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;

  const x = viewportWidth / 2 - centerX * zoom;
  const y = viewportHeight / 2 - centerY * zoom;

  return { x, y, zoom: Math.max(0.1, zoom) };
}

