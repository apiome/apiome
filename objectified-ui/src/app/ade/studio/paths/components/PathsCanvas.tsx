'use client';

import React, { useCallback, useState, useRef, useMemo, useEffect } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Panel,
  useReactFlow,
  ReactFlowProvider,
  Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import PathNode, { PathNodeData, PathVariable } from '@/app/components/ade/paths/PathNode';
import { getPathsForVersionAction, createPathAction, createOperationAction, getOperationsForPathAction } from '../actions';
import { useStudio } from '../../StudioContext';

interface PathsCanvasProps {
  onNodeSelect?: (node: any | null) => void;
  onNodeUpdate?: (nodeId: string, data: Partial<PathNodeData>) => void;
}

// Custom node types
const nodeTypes = {
  pathNode: PathNode,
};

// Generate unique IDs for nodes
let nodeIdCounter = 0;
const getNodeId = () => `node_${++nodeIdCounter}`;

function PathsCanvasInner({ onNodeSelect, onNodeUpdate }: PathsCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [showMiniMap, setShowMiniMap] = useState(true);
  const { screenToFlowPosition } = useReactFlow();
  const { selectedVersionId } = useStudio();

  // Load existing paths from database when version changes
  useEffect(() => {
    if (!selectedVersionId) {
      setNodes([]);
      setEdges([]);
      return;
    }

    const loadPaths = async () => {
      try {
        const result = await getPathsForVersionAction(selectedVersionId);
        const paths = JSON.parse(result);

        if (Array.isArray(paths) && paths.length > 0) {
          const allNodes: Node[] = [];
          const allEdges: any[] = [];

          // Load paths and their operations
          for (let index = 0; index < paths.length; index++) {
            const path = paths[index];

            // Create path node
            const pathNodeData: PathNodeData = {
              label: path.path,
              nodeType: 'path',
              dbPathId: path.id,
              path: path.path,
              summary: path.summary || '',
              description: path.description || '',
              tags: path.tags || [],
              deprecated: path.deprecated || false,
              pathVariables: [], // Will be extracted from path pattern
            };

            const pathNode: Node = {
              id: `db-path-${path.id}`,
              type: 'pathNode',
              position: { x: 100, y: 100 + index * 250 }, // More space for methods
              data: pathNodeData as unknown as Record<string, unknown>,
            };

            allNodes.push(pathNode);

            // Load operations for this path
            try {
              const opsResult = await getOperationsForPathAction(path.id);
              const operations = JSON.parse(opsResult);

              if (Array.isArray(operations) && operations.length > 0) {
                operations.forEach((op: any, opIndex: number) => {
                  // Create method node for each operation
                  const methodNodeData: PathNodeData = {
                    label: op.method.toUpperCase(),
                    nodeType: 'method',
                    dbOperationId: op.id,
                    connectedPathId: path.id,
                    method: op.method.toUpperCase(),
                    operationId: op.operation_id || '',
                    summary: op.summary || '',
                    description: op.description || '',
                    deprecated: op.deprecated || false,
                    pendingDbSave: false, // Already saved
                  };

                  const methodNode: Node = {
                    id: `db-operation-${op.id}`,
                    type: 'pathNode',
                    position: {
                      x: 100 + (opIndex * 180),
                      y: 100 + index * 250 + 120
                    }, // Position below path
                    data: methodNodeData as unknown as Record<string, unknown>,
                  };

                  allNodes.push(methodNode);

                  // Create edge from path to method
                  allEdges.push({
                    id: `edge-${path.id}-${op.id}`,
                    source: `db-path-${path.id}`,
                    target: `db-operation-${op.id}`,
                    type: 'default',
                  });
                });
              }
            } catch (error) {
              console.error(`Error loading operations for path ${path.id}:`, error);
            }
          }

          setNodes(allNodes);
          setEdges(allEdges);
        }
      } catch (error) {
        console.error('Error loading paths:', error);
      }
    };

    loadPaths();
  }, [selectedVersionId, setNodes, setEdges]);

  const onConnect = useCallback(
    async (params: Connection) => {
      setEdges((eds) => addEdge(params, eds));

      // If connecting a method to a path, set connectedPathId and try to save
      const sourceNode = nodes.find(n => n.id === params.source);
      const targetNode = nodes.find(n => n.id === params.target);

      // Check if source is path and target is method (path -> method)
      if (sourceNode?.data?.nodeType === 'path' && targetNode?.data?.nodeType === 'method') {
        const pathDbId = sourceNode.data.dbPathId as string | undefined;
        if (pathDbId && targetNode.data.pendingDbSave) {
          // Update the method node with the connected path
          setNodes((nds) =>
            nds.map((node) => {
              if (node.id === targetNode.id) {
                return {
                  ...node,
                  data: {
                    ...node.data,
                    connectedPathId: pathDbId,
                  },
                };
              }
              return node;
            })
          );

          // Try to save the operation to database
          try {
            const result = await createOperationAction(
              pathDbId,
              (targetNode.data.method as string) || 'get',
              (targetNode.data.operationId as string) || '',
              (targetNode.data.summary as string) || '',
              (targetNode.data.description as string) || '',
              undefined, // externalDocs
              false, // deprecated
              undefined // servers
            );
            const parsedResult = JSON.parse(result);
            if (parsedResult.success && parsedResult.operation) {
              // Update node with database ID
              setNodes((nds) =>
                nds.map((node) => {
                  if (node.id === targetNode.id) {
                    return {
                      ...node,
                      data: {
                        ...node.data,
                        dbOperationId: parsedResult.operation.id,
                        pendingDbSave: false,
                      },
                    };
                  }
                  return node;
                })
              );
            }
          } catch (error) {
            console.error('Error creating operation when connecting:', error);
          }
        }
      }
    },
    [setEdges, nodes, setNodes]
  );

  // Handle node click to select it
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect?.(node);
    },
    [onNodeSelect]
  );

  // Handle clicking on the canvas background to deselect
  const onPaneClick = useCallback(() => {
    onNodeSelect?.(null);
  }, [onNodeSelect]);

  // Handle drag over to allow drop
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // Update a node's data
  const updateNodeData = useCallback(
    (nodeId: string, newData: Partial<PathNodeData>) => {
      setNodes((nds) =>
        nds.map((node: Node) => {
          if (node.id === nodeId) {
            return {
              ...node,
              data: { ...node.data, ...newData },
            };
          }
          return node;
        })
      );
      onNodeUpdate?.(nodeId, newData);
    },
    [setNodes, onNodeUpdate]
  );

  // Handle drop from library
  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault();

      const data = event.dataTransfer.getData('application/reactflow');
      if (!data) return;

      try {
        const item = JSON.parse(data);

        // Get the position where the node was dropped
        const position = screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        // Create the new node based on the item type
        const nodeData: PathNodeData = {
          label: item.label,
          nodeType: item.type,
          color: item.color,
          // Path-specific data
          ...(item.type === 'path' && {
            path: '/api/v1/example',
            summary: '',
            description: '',
            tags: [],
            deprecated: false,
            pathVariables: [],
          }),
          // Method-specific data
          ...(item.type === 'method' && {
            method: item.id.toUpperCase(),
            operationId: '',
            summary: '',
            description: '',
            parameters: [],
            responses: [],
          }),
        };

        // Save to database if it's a path node and we have a version selected
        let dbPathId: string | undefined;
        if (item.type === 'path' && selectedVersionId) {
          try {
            const result = await createPathAction(
              selectedVersionId,
              nodeData.path || '/api/v1/example',
              nodeData.summary,
              nodeData.description,
              null, // servers
              null, // parameters (path-level parameters)
              0 // sort_order
            );
            const parsedResult = JSON.parse(result);
            if (parsedResult.success && parsedResult.path) {
              dbPathId = parsedResult.path.id;
              // Store the database ID in the node data
              nodeData.dbPathId = dbPathId;
            } else {
              console.error('Failed to create path in database:', parsedResult.error);
            }
          } catch (error) {
            console.error('Error creating path in database:', error);
          }
        }

        // Save to database if it's a method node and we have a version selected
        // Note: Methods need to be attached to a path, so for now we'll just create the node
        // The user will need to connect it to a path node later
        if (item.type === 'method' && selectedVersionId) {
          // We'll handle method creation when the user connects it to a path
          // or we can store it as pending and create it later
          nodeData.pendingDbSave = true;
        }

        const newNode: Node = {
          id: getNodeId(),
          type: 'pathNode',
          position,
          data: nodeData as unknown as Record<string, unknown>,
        };

        setNodes((nds) => nds.concat(newNode));

        // Automatically select the new node
        onNodeSelect?.(newNode);
      } catch (error) {
        console.error('Failed to parse dropped item:', error);
      }
    },
    [screenToFlowPosition, setNodes, onNodeSelect, selectedVersionId]
  );

  // Expose updateNodeData to parent through a ref or context
  // For now, we'll pass it through the onNodeSelect callback
  const handleNodeSelect = useCallback(
    (node: Node | null) => {
      if (node) {
        // Attach the update function to the node for the properties panel
        onNodeSelect?.({ ...node, updateData: (data: Partial<PathNodeData>) => updateNodeData(node.id, data) });
      } else {
        onNodeSelect?.(null);
      }
    },
    [onNodeSelect, updateNodeData]
  );

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      handleNodeSelect(node);
    },
    [handleNodeSelect]
  );

  return (
    <div ref={reactFlowWrapper} className="flex-1 relative h-full bg-gray-50 dark:bg-gray-900">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={onPaneClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        fitView
        className="bg-gray-50 dark:bg-gray-900"
      >
        <Background color="#aaa" gap={16} />
        <Controls className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg" />
        {showMiniMap && (
          <MiniMap
            className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg"
            nodeColor={() => '#6366f1'}
          />
        )}
        <Panel position="bottom-right" className="flex items-center gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-4 py-2 mr-2 mb-2 shadow-lg">
          <button
            onClick={() => setShowMiniMap(!showMiniMap)}
            className="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
          >
            {showMiniMap ? 'Hide' : 'Show'} Mini-map
          </button>
          <span className="text-gray-300 dark:text-gray-600">|</span>
          <span className="text-sm text-gray-600 dark:text-gray-400">
            Nodes: {nodes.length}
          </span>
        </Panel>
      </ReactFlow>
    </div>
  );
}

// Wrapper component that provides the ReactFlow context
export default function PathsCanvas({ onNodeSelect, onNodeUpdate }: PathsCanvasProps) {
  return (
    <ReactFlowProvider>
      <PathsCanvasInner onNodeSelect={onNodeSelect} onNodeUpdate={onNodeUpdate} />
    </ReactFlowProvider>
  );
}
