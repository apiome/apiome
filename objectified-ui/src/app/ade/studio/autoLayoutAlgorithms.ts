/**
 * Auto Layout Algorithms for Canvas
 *
 * This module provides various layout algorithms for arranging nodes on the canvas:
 * - Force-Directed Layout: Physics-based simulation for organic arrangement
 * - Hierarchical Layout: Top-down flow with root classes at top
 * - Circular Layout: Arrange classes in a circle
 * - Grid Layout: Snap all classes to a grid
 * - Layered Layout: Organize into horizontal layers by depth
 */

import type { Node, Edge } from '@xyflow/react';
import dagre from 'dagre';

export type LayoutAlgorithm =
  | 'hierarchical-tb'  // Hierarchical Top-Down (default dagre)
  | 'hierarchical-lr'  // Hierarchical Left-Right
  | 'hierarchical-bt'  // Hierarchical Bottom-Top
  | 'hierarchical-rl'  // Hierarchical Right-Left
  | 'force-directed'   // Force-Directed/Spring Layout
  | 'circular'         // Circular Layout
  | 'grid'             // Grid Layout
  | 'layered';         // Layered Layout

// Default node dimensions
const NODE_WIDTH = 280;
const NODE_HEIGHT = 180;

export interface LayoutOptions {
  algorithm?: LayoutAlgorithm;
  nodeWidth?: number;
  nodeHeight?: number;
  // For hierarchical layouts
  rankSeparation?: number;
  nodeSeparation?: number;
  edgeSeparation?: number;
  // For force-directed
  springStrength?: number;
  repulsionStrength?: number;
  iterations?: number;
  // For circular
  radius?: number;
  startAngle?: number;
  // For grid
  columns?: number;
  columnSpacing?: number;
  rowSpacing?: number;
  sortAlphabetically?: boolean;
  // For layered
  layerHeight?: number;
}

/**
 * Main layout function - dispatches to specific algorithm
 */
export function applyAutoLayout(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions = {}
): Node[] {
  const algorithm = options.algorithm || 'hierarchical-tb';

  switch (algorithm) {
    case 'hierarchical-tb':
      return hierarchicalLayout(nodes, edges, { ...options, direction: 'TB' });
    case 'hierarchical-lr':
      return hierarchicalLayout(nodes, edges, { ...options, direction: 'LR' });
    case 'hierarchical-bt':
      return hierarchicalLayout(nodes, edges, { ...options, direction: 'BT' });
    case 'hierarchical-rl':
      return hierarchicalLayout(nodes, edges, { ...options, direction: 'RL' });
    case 'force-directed':
      return forceDirectedLayout(nodes, edges, options);
    case 'circular':
      return circularLayout(nodes, edges, options);
    case 'grid':
      return gridLayout(nodes, edges, options);
    case 'layered':
      return layeredLayout(nodes, edges, options);
    default:
      return hierarchicalLayout(nodes, edges, { ...options, direction: 'TB' });
  }
}

/**
 * Get actual node width, using measured dimensions or default
 */
function getNodeWidth(node: Node, defaultWidth: number = NODE_WIDTH): number {
  return node.measured?.width ?? node.width ?? defaultWidth;
}

/**
 * Get actual node height, using measured dimensions or default
 */
function getNodeHeight(node: Node, defaultHeight: number = NODE_HEIGHT): number {
  return node.measured?.height ?? node.height ?? defaultHeight;
}

/**
 * Hierarchical Layout using Dagre
 * Top-down flow with root classes at top, dependencies flow downward
 */
function hierarchicalLayout(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions & { direction: 'TB' | 'LR' | 'BT' | 'RL' }
): Node[] {
  const {
    direction = 'TB',
    rankSeparation = 150,
    nodeSeparation = 100,
    edgeSeparation = 30,
  } = options;

  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: direction,
    ranksep: rankSeparation,
    nodesep: nodeSeparation,
    edgesep: edgeSeparation,
  });

  // Add nodes with their actual measured dimensions
  nodes.forEach((node) => {
    const width = getNodeWidth(node, options.nodeWidth);
    const height = getNodeHeight(node, options.nodeHeight);

    dagreGraph.setNode(node.id, {
      width,
      height,
    });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  // Position nodes using their actual dimensions for centering
  return nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const width = getNodeWidth(node, options.nodeWidth);
    const height = getNodeHeight(node, options.nodeHeight);

    // Dagre positions nodes from center, React Flow from top-left
    const x = nodeWithPosition.x - width / 2;
    const y = nodeWithPosition.y - height / 2;

    return {
      ...node,
      position: { x, y },
    };
  });
}

/**
 * Force-Directed Layout
 * Physics-based simulation where nodes repel and edges act as springs
 */
function forceDirectedLayout(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions
): Node[] {
  const {
    springStrength = 0.1,
    repulsionStrength = 3000,
    iterations = 100,
  } = options;

  // Create a map of node sizes for quick lookup
  const nodeSizes = new Map<string, { width: number; height: number }>();
  nodes.forEach((node) => {
    nodeSizes.set(node.id, {
      width: getNodeWidth(node, options.nodeWidth),
      height: getNodeHeight(node, options.nodeHeight),
    });
  });

  // Initialize node positions if they don't have any
  const nodeMap = new Map<string, { x: number; y: number; vx: number; vy: number }>();

  nodes.forEach((node, index) => {
    // Start with current position or use circle arrangement as starting point
    const angle = (2 * Math.PI * index) / nodes.length;
    const radius = Math.max(300, nodes.length * 30);

    nodeMap.set(node.id, {
      x: node.position?.x ?? Math.cos(angle) * radius,
      y: node.position?.y ?? Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
    });
  });

  // Build adjacency list for connected nodes
  const adjacencyList = new Map<string, Set<string>>();
  edges.forEach((edge) => {
    if (!adjacencyList.has(edge.source)) {
      adjacencyList.set(edge.source, new Set());
    }
    if (!adjacencyList.has(edge.target)) {
      adjacencyList.set(edge.target, new Set());
    }
    adjacencyList.get(edge.source)!.add(edge.target);
    adjacencyList.get(edge.target)!.add(edge.source);
  });

  // Run force simulation
  for (let iter = 0; iter < iterations; iter++) {
    // Calculate repulsion forces (all pairs)
    for (const [id1, pos1] of nodeMap.entries()) {
      const size1 = nodeSizes.get(id1)!;

      for (const [id2, pos2] of nodeMap.entries()) {
        if (id1 === id2) continue;

        const size2 = nodeSizes.get(id2)!;

        const dx = pos1.x - pos2.x;
        const dy = pos1.y - pos2.y;
        const distanceSquared = dx * dx + dy * dy;
        const distance = Math.sqrt(distanceSquared) || 1;

        // Consider node sizes in repulsion - larger nodes need more space
        const avgSize = ((size1.width + size1.height + size2.width + size2.height) / 4);
        const minDistance = avgSize * 0.8; // Minimum distance based on node sizes

        // Stronger repulsion if nodes are too close
        const effectiveRepulsion = distance < minDistance
          ? repulsionStrength * 2
          : repulsionStrength;

        // Coulomb's law for repulsion
        const force = effectiveRepulsion / (distanceSquared || 1);
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;

        pos1.vx += fx;
        pos1.vy += fy;
      }
    }

    // Calculate spring forces (connected nodes)
    edges.forEach((edge) => {
      const source = nodeMap.get(edge.source);
      const target = nodeMap.get(edge.target);
      if (!source || !target) return;

      const sourceSize = nodeSizes.get(edge.source)!;
      const targetSize = nodeSizes.get(edge.target)!;

      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.sqrt(dx * dx + dy * dy) || 1;

      // Ideal spring length based on node sizes
      const avgNodeSize = (sourceSize.width + sourceSize.height + targetSize.width + targetSize.height) / 4;
      const idealLength = Math.max(200, avgNodeSize * 1.5);
      const displacement = distance - idealLength;

      // Hooke's law for spring force
      const force = springStrength * displacement;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;

      source.vx += fx;
      source.vy += fy;
      target.vx -= fx;
      target.vy -= fy;
    });

    // Apply velocities with damping
    const damping = 0.8;
    for (const pos of nodeMap.values()) {
      pos.x += pos.vx;
      pos.y += pos.vy;
      pos.vx *= damping;
      pos.vy *= damping;
    }
  }

  // Center the layout
  const positions = Array.from(nodeMap.values());
  const avgX = positions.reduce((sum, p) => sum + p.x, 0) / positions.length;
  const avgY = positions.reduce((sum, p) => sum + p.y, 0) / positions.length;

  // Position nodes using their actual dimensions
  return nodes.map((node) => {
    const pos = nodeMap.get(node.id);
    if (!pos) return node;

    const width = getNodeWidth(node, options.nodeWidth);
    const height = getNodeHeight(node, options.nodeHeight);

    return {
      ...node,
      position: {
        x: pos.x - avgX - width / 2,
        y: pos.y - avgY - height / 2,
      },
    };
  });
}

/**
 * Circular Layout
 * Arrange all nodes in a circle
 */
function circularLayout(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions
): Node[] {
  if (nodes.length === 0) return nodes;
  if (nodes.length === 1) {
    return [{
      ...nodes[0],
      position: { x: 0, y: 0 },
    }];
  }

  // Calculate average node size to determine appropriate radius
  const avgNodeSize = nodes.reduce((sum, node) => {
    const width = getNodeWidth(node, options.nodeWidth);
    const height = getNodeHeight(node, options.nodeHeight);
    return sum + (width + height) / 2;
  }, 0) / nodes.length;

  // Calculate radius based on number of nodes and their sizes
  // Ensure enough space between nodes on the circumference
  const circumference = nodes.length * avgNodeSize * 1.8; // 1.8x for spacing
  const calculatedRadius = circumference / (2 * Math.PI);

  const {
    radius = Math.max(400, calculatedRadius),
    startAngle = -Math.PI / 2, // Start at top
  } = options;

  // Try to place more connected nodes closer together
  const orderedNodes = orderNodesByConnectivity(nodes, edges);

  return orderedNodes.map((node, index) => {
    const angle = startAngle + (2 * Math.PI * index) / orderedNodes.length;
    const x = Math.cos(angle) * radius;
    const y = Math.sin(angle) * radius;

    const width = getNodeWidth(node, options.nodeWidth);
    const height = getNodeHeight(node, options.nodeHeight);

    return {
      ...node,
      position: {
        x: x - width / 2,
        y: y - height / 2,
      },
    };
  });
}

/**
 * Grid Layout
 * Arrange nodes in a regular grid
 */
function gridLayout(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions
): Node[] {
  const {
    columns = Math.ceil(Math.sqrt(nodes.length)),
    columnSpacing = 350,
    rowSpacing = 250,
    sortAlphabetically = true,
  } = options;

  if (nodes.length === 0) return nodes;

  // Sort nodes if requested
  const sortedNodes = sortAlphabetically
    ? [...nodes].sort((a, b) => {
        const nameA = (a.data?.label || a.id).toString().toLowerCase();
        const nameB = (b.data?.label || b.id).toString().toLowerCase();
        return nameA.localeCompare(nameB);
      })
    : nodes;

  // Calculate maximum width for each column and maximum height for each row
  const numRows = Math.ceil(sortedNodes.length / columns);
  const maxColumnWidths = new Array(columns).fill(0);
  const maxRowHeights = new Array(numRows).fill(0);

  sortedNodes.forEach((node, index) => {
    const col = index % columns;
    const row = Math.floor(index / columns);
    const width = getNodeWidth(node, options.nodeWidth);
    const height = getNodeHeight(node, options.nodeHeight);

    maxColumnWidths[col] = Math.max(maxColumnWidths[col], width);
    maxRowHeights[row] = Math.max(maxRowHeights[row], height);
  });

  // Calculate cumulative positions
  const columnPositions = [0];
  for (let i = 0; i < columns - 1; i++) {
    columnPositions.push(columnPositions[i] + maxColumnWidths[i] + columnSpacing);
  }

  const rowPositions = [0];
  for (let i = 0; i < numRows - 1; i++) {
    rowPositions.push(rowPositions[i] + maxRowHeights[i] + rowSpacing);
  }

  return sortedNodes.map((node, index) => {
    const col = index % columns;
    const row = Math.floor(index / columns);

    return {
      ...node,
      position: {
        x: columnPositions[col],
        y: rowPositions[row],
      },
    };
  });
}

/**
 * Layered Layout
 * Organize nodes into horizontal layers based on dependency depth
 */
function layeredLayout(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions
): Node[] {
  const {
    layerHeight = 250,
    nodeSeparation = 350,
  } = options;

  if (nodes.length === 0) return nodes;

  // Build adjacency list (dependencies)
  const outgoingEdges = new Map<string, Set<string>>();
  const incomingEdges = new Map<string, Set<string>>();

  nodes.forEach(node => {
    outgoingEdges.set(node.id, new Set());
    incomingEdges.set(node.id, new Set());
  });

  edges.forEach(edge => {
    outgoingEdges.get(edge.source)?.add(edge.target);
    incomingEdges.get(edge.target)?.add(edge.source);
  });

  // Find root nodes (no incoming edges)
  const rootNodes = nodes.filter(node =>
    incomingEdges.get(node.id)?.size === 0
  );

  // If no root nodes (circular dependencies), use all nodes as roots
  const startNodes = rootNodes.length > 0 ? rootNodes : nodes;

  // Assign layers using BFS
  const nodeToLayer = new Map<string, number>();
  const visited = new Set<string>();
  const queue: { id: string; layer: number }[] = [];

  startNodes.forEach(node => {
    queue.push({ id: node.id, layer: 0 });
    visited.add(node.id);
  });

  while (queue.length > 0) {
    const { id, layer } = queue.shift()!;
    nodeToLayer.set(id, layer);

    const children = outgoingEdges.get(id) || new Set();
    children.forEach(childId => {
      if (!visited.has(childId)) {
        visited.add(childId);
        queue.push({ id: childId, layer: layer + 1 });
      } else {
        // Update layer to be deeper if we found a longer path
        const currentLayer = nodeToLayer.get(childId) || 0;
        if (layer + 1 > currentLayer) {
          nodeToLayer.set(childId, layer + 1);
        }
      }
    });
  }

  // Handle disconnected nodes
  nodes.forEach(node => {
    if (!nodeToLayer.has(node.id)) {
      nodeToLayer.set(node.id, 0);
    }
  });

  // Group nodes by layer
  const layers = new Map<number, Node[]>();
  nodes.forEach(node => {
    const layer = nodeToLayer.get(node.id) || 0;
    if (!layers.has(layer)) {
      layers.set(layer, []);
    }
    layers.get(layer)!.push(node);
  });

  // Calculate maximum height for each layer
  const maxLayerHeights = new Map<number, number>();
  nodes.forEach(node => {
    const layer = nodeToLayer.get(node.id) || 0;
    const height = getNodeHeight(node, options.nodeHeight);
    const currentMax = maxLayerHeights.get(layer) || 0;
    maxLayerHeights.set(layer, Math.max(currentMax, height));
  });

  // Calculate cumulative Y positions for each layer
  const layerCount = Math.max(...Array.from(nodeToLayer.values())) + 1;
  const layerYPositions = [0];
  for (let i = 0; i < layerCount - 1; i++) {
    const prevHeight = maxLayerHeights.get(i) || 0;
    layerYPositions.push(layerYPositions[i] + prevHeight + layerHeight);
  }

  // Position nodes
  return nodes.map(node => {
    const layer = nodeToLayer.get(node.id) || 0;
    const nodesInLayer = layers.get(layer) || [];
    const indexInLayer = nodesInLayer.indexOf(node);

    // Calculate total width of layer considering actual node widths
    let totalLayerWidth = 0;
    nodesInLayer.forEach((n, idx) => {
      totalLayerWidth += getNodeWidth(n, options.nodeWidth);
      if (idx < nodesInLayer.length - 1) {
        totalLayerWidth += nodeSeparation;
      }
    });

    // Calculate X position
    let xPosition = -totalLayerWidth / 2;
    for (let i = 0; i < indexInLayer; i++) {
      xPosition += getNodeWidth(nodesInLayer[i], options.nodeWidth) + nodeSeparation;
    }

    return {
      ...node,
      position: {
        x: xPosition,
        y: layerYPositions[layer],
      },
    };
  });
}

/**
 * Helper function to order nodes by connectivity
 * Nodes with more connections are placed closer together
 */
function orderNodesByConnectivity(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  // Build adjacency list
  const adjacencyList = new Map<string, Set<string>>();
  nodes.forEach(node => {
    adjacencyList.set(node.id, new Set());
  });

  edges.forEach(edge => {
    adjacencyList.get(edge.source)?.add(edge.target);
    adjacencyList.get(edge.target)?.add(edge.source);
  });

  // Start with the most connected node
  const ordered: Node[] = [];
  const remaining = new Set(nodes);

  // Find most connected node
  let currentNode = nodes.reduce((max, node) => {
    const connections = adjacencyList.get(node.id)?.size || 0;
    const maxConnections = adjacencyList.get(max.id)?.size || 0;
    return connections > maxConnections ? node : max;
  }, nodes[0]);

  // Add nodes by proximity to already added nodes
  while (remaining.size > 0) {
    ordered.push(currentNode);
    remaining.delete(currentNode);

    if (remaining.size === 0) break;

    // Find next node: prefer connected to current node
    const neighbors = Array.from(adjacencyList.get(currentNode.id) || [])
      .map(id => nodes.find(n => n.id === id))
      .filter(n => n && remaining.has(n)) as Node[];

    if (neighbors.length > 0) {
      // Pick neighbor with most connections
      currentNode = neighbors.reduce((max, node) => {
        const connections = adjacencyList.get(node.id)?.size || 0;
        const maxConnections = adjacencyList.get(max.id)?.size || 0;
        return connections > maxConnections ? node : max;
      }, neighbors[0]);
    } else {
      // No neighbors, pick any remaining node (most connected)
      currentNode = Array.from(remaining).reduce((max, node) => {
        const connections = adjacencyList.get(node.id)?.size || 0;
        const maxConnections = adjacencyList.get(max.id)?.size || 0;
        return connections > maxConnections ? node : max;
      }, Array.from(remaining)[0]);
    }
  }

  return ordered;
}

/**
 * Get human-readable name for layout algorithm
 */
export function getLayoutAlgorithmName(algorithm: LayoutAlgorithm): string {
  switch (algorithm) {
    case 'hierarchical-tb':
      return 'Hierarchical (Top-Down)';
    case 'hierarchical-lr':
      return 'Hierarchical (Left-Right)';
    case 'hierarchical-bt':
      return 'Hierarchical (Bottom-Top)';
    case 'hierarchical-rl':
      return 'Hierarchical (Right-Left)';
    case 'force-directed':
      return 'Force-Directed';
    case 'circular':
      return 'Circular';
    case 'grid':
      return 'Grid';
    case 'layered':
      return 'Layered';
    default:
      return 'Unknown';
  }
}

/**
 * Get description for layout algorithm
 */
export function getLayoutAlgorithmDescription(algorithm: LayoutAlgorithm): string {
  switch (algorithm) {
    case 'hierarchical-tb':
    case 'hierarchical-lr':
    case 'hierarchical-bt':
    case 'hierarchical-rl':
      return 'Organizes nodes in a hierarchy with dependencies flowing in one direction';
    case 'force-directed':
      return 'Physics-based simulation where connected nodes attract and unconnected nodes repel';
    case 'circular':
      return 'Arranges all nodes in a circle, good for showing cyclic dependencies';
    case 'grid':
      return 'Places nodes in a regular grid pattern, alphabetically ordered';
    case 'layered':
      return 'Organizes nodes into horizontal layers based on dependency depth';
    default:
      return '';
  }
}

