import dagre from 'dagre';
import type { Node, Edge } from '@xyflow/react';

export type LayoutDirection = 'TB' | 'BT' | 'LR' | 'RL';

// Default node dimensions
const NODE_WIDTH = 280;
const NODE_HEIGHT = 180;

export interface LayoutOptions {
  direction?: LayoutDirection;
  nodeWidth?: number;
  nodeHeight?: number;
  rankSeparation?: number;
  nodeSeparation?: number;
  edgeSeparation?: number;
}

/**
 * Layout nodes and edges using Dagre
 * @param nodes - Array of nodes to layout
 * @param edges - Array of edges connecting the nodes
 * @param options - Layout configuration options
 * @returns Array of nodes with updated positions
 */
export function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions = {}
): Node[] {
  const {
    direction = 'TB',
    nodeWidth = NODE_WIDTH,
    nodeHeight = NODE_HEIGHT,
    rankSeparation = 100,    // Increased from 150 for better vertical spacing
    nodeSeparation = 100,    // Increased from 120 for better horizontal spacing
    edgeSeparation = 30,     // Increased from 20 for better edge spacing
  } = options;

  // Create a new directed graph
  const dagreGraph = new dagre.graphlib.Graph();

  // Set graph configuration
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: direction,
    ranksep: rankSeparation,
    nodesep: nodeSeparation,
    edgesep: edgeSeparation,
  });

  // Add nodes to the graph
  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, {
      width: node.measured?.width ?? nodeWidth,
      height: node.measured?.height ?? nodeHeight,
    });
  });

  // Add edges to the graph
  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  // Run the layout algorithm
  dagre.layout(dagreGraph);

  // Update node positions based on layout
  return nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);

    // Dagre positions nodes from center, React Flow from top-left
    // So we need to adjust the position
    const x = nodeWithPosition.x - (node.measured?.width ?? nodeWidth) / 2;
    const y = nodeWithPosition.y - (node.measured?.height ?? nodeHeight) / 2;

    return {
      ...node,
      position: { x, y },
    };
  });
}

/**
 * Applies horizontal layout (left to right)
 */
export function getHorizontalLayout(nodes: Node[], edges: Edge[]): Node[] {
  return getLayoutedElements(nodes, edges, { direction: 'LR' });
}

/**
 * Applies vertical layout (top to bottom)
 */
export function getVerticalLayout(nodes: Node[], edges: Edge[]): Node[] {
  return getLayoutedElements(nodes, edges, { direction: 'TB' });
}

