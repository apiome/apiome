'use client';

import React, { useCallback, useState, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  ReactFlowProvider,
  useReactFlow,
  Handle,
  Position,
  addEdge,
  Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useStudio } from '../../StudioContext';
import { useDialog } from '../../../../components/providers/DialogProvider';
import SmartEdge from '../../../../components/ade/studio/SmartEdge';
import {
  getOperationsForPath,
  createOperation,
  deleteOperation,
} from '../../../../../../lib/db/helper-path-operations';
import {
  getLinkedParametersForOperation,
  linkParameterToOperation,
  unlinkParameterFromOperation,
  getSharedPathParameters,
  deleteSharedPathParameter,
} from '../../../../../../lib/db/helper-shared-path-parameters';
import {
  getLinkedResponsesForOperation,
  getSharedPathResponses,
  deleteSharedPathResponse,
  unlinkResponseFromOperation,
  linkResponseToOperation,
} from '../../../../../../lib/db/helper-shared-path-responses';
import PathParameterNode from './PathParameterNode';
import PathResponseNode from './PathResponseNode';
import { Trash2 } from 'lucide-react';

// Operation Node Component with Handle and Delete button
function OperationNode({ data }: { data: { operation: string; color: string; onDelete?: () => void } }) {
  return (
    <>
      <div
        className="px-4 py-2 rounded-lg shadow-lg border-2 font-bold text-white text-sm cursor-pointer relative group"
        style={{
          backgroundColor: data.color,
          borderColor: data.color,
          minWidth: '80px',
          textAlign: 'center',
        }}
      >
        {data.operation}
        {data.onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity shadow-lg hover:bg-red-600"
            title="Delete operation"
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        id="operation-output"
        className="w-3 h-3 bg-white/80 border-2"
        style={{ borderColor: data.color }}
      />
    </>
  );
}

const nodeTypes = {
  operation: OperationNode,
  parameter: PathParameterNode,
  response: PathResponseNode,
};

// Define custom edge types
const edgeTypes = {
  smart: SmartEdge,
};

// Operation color mapping
const OPERATION_COLORS: Record<string, string> = {
  'GET': '#10b981',
  'POST': '#3b82f6',
  'PUT': '#f59e0b',
  'PATCH': '#8b5cf6',
  'DELETE': '#ef4444',
  'HEAD': '#6b7280',
  'OPTIONS': '#64748b',
};

interface PathsCanvasInnerProps {
  selectedPathId: string | null;
  onOperationSelect: (operation: { id: string; operation: string } | null) => void;
  onParameterSelect?: (parameter: { id: string; name: string; operationId: string } | null) => void;
  refreshKey?: number;
  onRefresh?: () => void;
}

function PathsCanvasInner({ selectedPathId, onOperationSelect, onParameterSelect, refreshKey, onRefresh }: PathsCanvasInnerProps) {
  const {
    gridSize,
    gridStyle,
    snapToGrid,
    edgeRouting,
    edgeAnimation,
  } = useStudio();

  const { alert: alertDialog } = useDialog();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isDark, setIsDark] = useState(false);
  const { screenToFlowPosition } = useReactFlow();
  const { confirm: confirmDialog } = useDialog();

  // Handle delete operation
  const handleDeleteOperation = useCallback(async (operationId: string, operationName: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Operation',
      message: `Are you sure you want to delete the ${operationName} operation? This will also unlink all parameters from it.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      await deleteOperation(operationId);

      // Remove from UI
      setNodes((nds) => nds.filter((n) => n.id !== operationId));
      setEdges((eds) => eds.filter((e) => e.source !== operationId && e.target !== operationId));

      if (onRefresh) {
        onRefresh();
      }
    } catch (error) {
      console.error('Error deleting operation:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete operation',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, setNodes, setEdges, onRefresh]);

  // Handle delete parameter
  const handleDeleteParameter = useCallback(async (parameterId: string, parameterName: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Parameter',
      message: `Are you sure you want to delete the parameter "${parameterName}"? This will remove it from all operations.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteSharedPathParameter(parameterId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Remove from UI
        setNodes((nds) => nds.filter((n) => n.id !== `param-${parameterId}`));
        setEdges((eds) => eds.filter((e) => e.target !== `param-${parameterId}` && e.source !== `param-${parameterId}`));

        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to delete parameter',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error deleting parameter:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete parameter',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, setNodes, setEdges, onRefresh]);

  // Handle delete response
  const handleDeleteResponse = useCallback(async (responseId: string, statusCode: string, operationId: string) => {
    const confirmed = await confirmDialog({
      title: 'Unlink Response',
      message: `Are you sure you want to unlink the ${statusCode} response from this operation? The response will still be available for other operations.`,
      variant: 'danger',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await unlinkResponseFromOperation(operationId, responseId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Refresh the canvas to reload all data
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to unlink response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error unlinking response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to unlink response',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, onRefresh]);

  // Load operations and parameters when path is selected
  useEffect(() => {
    if (!selectedPathId) {
      setNodes([]);
      setEdges([]);
      return;
    }

    const loadOperationsAndParameters = async () => {
      try {
        // Load operations
        const operationsResponse = await getOperationsForPath(selectedPathId);
        const operations = JSON.parse(operationsResponse);

        // Convert operations to nodes with delete callback
        const operationNodes: Node[] = operations.map((op: any, index: number) => ({
          id: op.id,
          type: 'operation',
          position: { x: 100 + (index * 150), y: 100 },
          data: {
            operation: op.operation,
            color: OPERATION_COLORS[op.operation] || '#64748b',
            dbOperationId: op.id,
            onDelete: () => handleDeleteOperation(op.id, op.operation),
          },
        }));

        // Load ALL shared parameters for this path (not just linked ones)
        const allParamsResponse = await getSharedPathParameters(selectedPathId);
        const allParamsData = JSON.parse(allParamsResponse);

        const allParameterNodes: Node[] = [];
        const allEdges: Edge[] = [];

        if (allParamsData.success && allParamsData.parameters) {
          // Create nodes for all parameters
          allParamsData.parameters.forEach((param: any, paramIndex: number) => {
            const paramNodeId = `param-${param.id}`;

            allParameterNodes.push({
              id: paramNodeId,
              type: 'parameter',
              position: {
                x: 400,
                y: 100 + (paramIndex * 150),
              },
              data: {
                name: param.name,
                inLocation: param.in_location,
                summary: param.summary,
                description: param.description,
                required: param.data?.required ?? (param.in_location === 'path'),
                dbParameterId: param.id,
                onDelete: () => handleDeleteParameter(param.id, param.name),
              },
            });
          });
        }

        // Now load linked parameters to create edges
        for (const op of operations) {
          const paramsResponse = await getLinkedParametersForOperation(op.id);
          const paramsData = JSON.parse(paramsResponse);

          if (paramsData.success && paramsData.parameters) {
            paramsData.parameters.forEach((param: any) => {
              const paramNodeId = `param-${param.id}`;

              // Create edge from operation to parameter
              const edgeType = edgeRouting === 'straight' ? 'straight'
                : edgeRouting === 'bezier' ? 'default'
                : edgeRouting === 'smart' ? 'smart'
                : 'smoothstep';

              allEdges.push({
                id: `edge-${op.id}-${param.id}`,
                source: op.id,
                sourceHandle: 'operation-output',
                target: paramNodeId,
                targetHandle: 'parameter-input',
                type: edgeType,
                animated: edgeAnimation !== 'none',
                style: {
                  stroke: '#9ca3af',
                  strokeWidth: 2,
                  strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
                },
                data: {
                  sourceNodeId: op.id,
                  targetNodeId: paramNodeId,
                },
              });
            });
          }
        }

        // Now load responses for all operations and create response nodes
        // Load ALL shared responses for this path (not just linked ones)
        const allResponsesResponse = await getSharedPathResponses(selectedPathId);
        const allResponsesData = JSON.parse(allResponsesResponse);

        const allResponseNodes: Node[] = [];

        if (allResponsesData.success && allResponsesData.responses) {
          // Create nodes for all responses
          allResponsesData.responses.forEach((response: any, responseIndex: number) => {
            const responseNodeId = `response-${response.id}`;

            allResponseNodes.push({
              id: responseNodeId,
              type: 'response',
              position: {
                x: 700,
                y: 100 + (responseIndex * 150),
              },
              data: {
                statusCode: response.status_code,
                description: response.description,
                dbResponseId: response.id,
                // No onDelete - responses are shared, unlink via edges or properties panel
              },
            });
          });
        }

        // Now load linked responses to create edges
        for (const op of operations) {
          const linkedResponsesResponse = await getLinkedResponsesForOperation(op.id);
          const linkedResponsesData = JSON.parse(linkedResponsesResponse);

          if (linkedResponsesData.success && linkedResponsesData.responses) {
            linkedResponsesData.responses.forEach((response: any) => {
              const responseNodeId = `response-${response.id}`;

              // Create edge from operation to response
              const edgeType = edgeRouting === 'straight' ? 'straight'
                : edgeRouting === 'bezier' ? 'default'
                : edgeRouting === 'smart' ? 'smart'
                : 'smoothstep';

              allEdges.push({
                id: `edge-op-resp-${op.id}-${response.id}`,
                source: op.id,
                sourceHandle: 'operation-output',
                target: responseNodeId,
                targetHandle: 'response-input',
                type: edgeType,
                animated: edgeAnimation !== 'none',
                style: {
                  stroke: '#a78bfa',
                  strokeWidth: 2,
                  strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
                },
                data: {
                  sourceNodeId: op.id,
                  targetNodeId: responseNodeId,
                },
              });
            });
          }
        }

        setNodes([...operationNodes, ...allParameterNodes, ...allResponseNodes]);
        setEdges(allEdges);
      } catch (error) {
        console.error('Error loading operations and parameters:', error);
      }
    };

    loadOperationsAndParameters();
  }, [selectedPathId, setNodes, setEdges, refreshKey, edgeRouting, edgeAnimation, handleDeleteOperation, handleDeleteParameter, handleDeleteResponse]);

  // Detect dark mode
  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };
    checkDarkMode();

    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, []);

  // Get background variant
  const backgroundVariant = useCallback((style: 'dots' | 'lines' | 'cross'): BackgroundVariant => {
    switch (style) {
      case 'dots': return BackgroundVariant.Dots;
      case 'lines': return BackgroundVariant.Lines;
      case 'cross': return BackgroundVariant.Cross;
      default: return BackgroundVariant.Dots;
    }
  }, []);

  // Handle drag over
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  // Handle node click to show properties in sidebar
  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (node.type === 'operation') {
        onOperationSelect({
          id: node.data.dbOperationId as string,
          operation: node.data.operation as string,
        });
        if (onParameterSelect) {
          onParameterSelect(null);
        }
      } else if (node.type === 'parameter') {
        if (onParameterSelect) {
          onParameterSelect({
            id: node.data.dbParameterId as string,
            name: node.data.name as string,
            operationId: node.data.operationId as string,
          });
        }
        onOperationSelect(null);
      }
    },
    [onOperationSelect, onParameterSelect]
  );

  // Handle connecting nodes
  const onConnect = useCallback(
    async (connection: Connection) => {
      // Get edge type based on settings
      const edgeType = edgeRouting === 'straight' ? 'straight'
        : edgeRouting === 'bezier' ? 'default'
        : edgeRouting === 'smart' ? 'smart'
        : 'smoothstep';

      // Add edge to UI first
      setEdges((eds) => addEdge({
        ...connection,
        type: edgeType,
        animated: edgeAnimation !== 'none',
        style: {
          stroke: '#9ca3af',
          strokeWidth: 2,
          strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
        },
        data: {
          sourceNodeId: connection.source,
          targetNodeId: connection.target,
        },
      }, eds));

      // Save link to database if connecting operation to parameter or response (either direction)
      if (connection.source && connection.target) {
        const sourceNode = nodes.find(n => n.id === connection.source);
        const targetNode = nodes.find(n => n.id === connection.target);

        let operationId: string | undefined;
        let parameterId: string | undefined;
        let responseId: string | undefined;

        // Check if we're connecting operation to parameter (either direction)
        if (sourceNode?.type === 'operation' && targetNode?.type === 'parameter') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          parameterId = (targetNode.data as any)?.dbParameterId;
        } else if (sourceNode?.type === 'parameter' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          parameterId = (sourceNode.data as any)?.dbParameterId;
        }
        // Check if we're connecting operation to response (either direction)
        else if (sourceNode?.type === 'operation' && targetNode?.type === 'response') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          responseId = (targetNode.data as any)?.dbResponseId;
        } else if (sourceNode?.type === 'response' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          responseId = (sourceNode.data as any)?.dbResponseId;
        }

        // Handle parameter linking
        if (operationId && parameterId) {
          try {
            const result = await linkParameterToOperation(operationId, parameterId, undefined);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to link parameter to operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to link parameter to operation',
                variant: 'error',
              });
              // Remove the edge from UI since DB save failed
              setEdges((eds) => eds.filter(e =>
                !(e.source === connection.source && e.target === connection.target)
              ));
            }
          } catch (error) {
            console.error('Error linking parameter to operation:', error);
            await alertDialog({
              title: 'Error',
              message: 'Failed to link parameter to operation',
              variant: 'error',
            });
            // Remove the edge from UI since DB save failed
            setEdges((eds) => eds.filter(e =>
              !(e.source === connection.source && e.target === connection.target)
            ));
          }
        }
        // Handle response linking
        else if (operationId && responseId) {
          try {
            const result = await linkResponseToOperation(operationId, responseId, undefined);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to link response to operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to link response to operation',
                variant: 'error',
              });
              // Remove the edge from UI since DB save failed
              setEdges((eds) => eds.filter(e =>
                !(e.source === connection.source && e.target === connection.target)
              ));
            }
          } catch (error) {
            console.error('Error linking response to operation:', error);
            await alertDialog({
              title: 'Error',
              message: 'Failed to link response to operation',
              variant: 'error',
            });
            // Remove the edge from UI since DB save failed
            setEdges((eds) => eds.filter(e =>
              !(e.source === connection.source && e.target === connection.target)
            ));
          }
        }
      }
    },
    [setEdges, nodes, alertDialog, edgeRouting, edgeAnimation]
  );

  // Handle deleting edges (unlinking parameters and responses from operations)
  const onEdgesDelete = useCallback(
    async (edgesToDelete: Edge[]) => {
      for (const edge of edgesToDelete) {
        const sourceNode = nodes.find(n => n.id === edge.source);
        const targetNode = nodes.find(n => n.id === edge.target);

        let operationId: string | undefined;
        let parameterId: string | undefined;
        let responseId: string | undefined;

        // Check if we're unlinking operation from parameter (either direction)
        if (sourceNode?.type === 'operation' && targetNode?.type === 'parameter') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          parameterId = (targetNode.data as any)?.dbParameterId;
        } else if (sourceNode?.type === 'parameter' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          parameterId = (sourceNode.data as any)?.dbParameterId;
        }
        // Check if we're unlinking operation from response (either direction)
        else if (sourceNode?.type === 'operation' && targetNode?.type === 'response') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          responseId = (targetNode.data as any)?.dbResponseId;
        } else if (sourceNode?.type === 'response' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          responseId = (sourceNode.data as any)?.dbResponseId;
        }

        // Handle parameter unlinking
        if (operationId && parameterId) {
          try {
            const result = await unlinkParameterFromOperation(operationId, parameterId);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to unlink parameter from operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to unlink parameter from operation',
                variant: 'error',
              });
            }
          } catch (error) {
            console.error('Error unlinking parameter from operation:', error);
          }
        }
        // Handle response unlinking
        else if (operationId && responseId) {
          try {
            const result = await unlinkResponseFromOperation(operationId, responseId);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to unlink response from operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to unlink response from operation',
                variant: 'error',
              });
            }
          } catch (error) {
            console.error('Error unlinking response from operation:', error);
          }
        }
      }
    },
    [nodes, alertDialog]
  );

  // Handle drop
  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault();

      if (!selectedPathId) {
        await alertDialog({
          title: 'No Path Selected',
          message: 'Please select a path from the sidebar before adding operations to the canvas.',
          variant: 'warning',
        });
        return;
      }

      const data = event.dataTransfer.getData('application/json');
      if (!data) return;

      const dropData = JSON.parse(data);

      if (dropData.type === 'operation') {
        const position = screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        try {
          // Save to database
          const result = await createOperation(
            selectedPathId,
            dropData.operation,
            { position }
          );
          const savedOperation = JSON.parse(result);

          // Add to canvas
          const newNode: Node = {
            id: savedOperation.id,
            type: 'operation',
            position,
            data: {
              operation: savedOperation.operation,
              color: dropData.color,
              dbOperationId: savedOperation.id,
            },
          };

          setNodes((nds) => [...nds, newNode]);
        } catch (error) {
          console.error('Error creating operation:', error);
          await alertDialog({
            title: 'Error',
            message: 'Failed to add operation. Please try again.',
            variant: 'error',
          });
        }
      } else if (dropData.type === 'parameter') {
        await alertDialog({
          title: 'Add Parameter via Properties Panel',
          message: 'To add a parameter, click on an operation node and use the "Add Parameter" button in the Operation Details panel on the right.',
          variant: 'info',
        });
      }
    },
    [screenToFlowPosition, setNodes, selectedPathId, alertDialog]
  );

  return (
    <div ref={reactFlowWrapper} className="flex-1 flex flex-col h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onEdgesDelete={onEdgesDelete}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        snapToGrid={snapToGrid}
        snapGrid={[gridSize, gridSize]}
        fitView
        attributionPosition="bottom-left"
        className={isDark ? 'bg-gray-900' : ''}
        nodesDraggable={true}
        nodesConnectable={true}
        elementsSelectable={true}
        selectionOnDrag={true}
        nodesFocusable={true}
        edgesFocusable={true}
        style={{
          background: isDark
            ? 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)'
            : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #e2e8f0 100%)'
        }}
      >
        <Background
          variant={backgroundVariant(gridStyle)}
          gap={gridSize}
          size={1.5}
          color="currentColor"
          style={{
            color: 'rgb(99, 102, 241)',
            opacity: isDark ? 0.25 : 0.15
          }}
        />
        <Controls
          className="bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden"
          style={{
            borderRadius: '12px',
            overflow: 'hidden',
          }}
        />
      </ReactFlow>
    </div>
  );
}

export default function PathsCanvasView({
  selectedPathId,
  onOperationSelect,
  onParameterSelect,
  refreshKey,
  onRefresh,
}: {
  selectedPathId: string | null;
  onOperationSelect: (operation: { id: string; operation: string } | null) => void;
  onParameterSelect?: (parameter: { id: string; name: string; operationId: string } | null) => void;
  refreshKey?: number;
  onRefresh?: () => void;
}) {
  return (
    <ReactFlowProvider>
      <PathsCanvasInner
        selectedPathId={selectedPathId}
        onOperationSelect={onOperationSelect}
        onParameterSelect={onParameterSelect}
        refreshKey={refreshKey}
        onRefresh={onRefresh}
      />
    </ReactFlowProvider>
  );
}
