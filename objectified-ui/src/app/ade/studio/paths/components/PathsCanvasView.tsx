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
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useStudio } from '../../StudioContext';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  getOperationsForPath,
  createOperation,
} from '../../../../../../lib/db/helper-path-operations';

// Operation Node Component
function OperationNode({ data }: { data: { operation: string; color: string } }) {
  return (
    <div
      className="px-4 py-2 rounded-lg shadow-lg border-2 font-bold text-white text-sm"
      style={{
        backgroundColor: data.color,
        borderColor: data.color,
        minWidth: '80px',
        textAlign: 'center',
      }}
    >
      {data.operation}
    </div>
  );
}

const nodeTypes = {
  operation: OperationNode,
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
}

function PathsCanvasInner({ selectedPathId, onOperationSelect }: PathsCanvasInnerProps) {
  const {
    gridSize,
    gridStyle,
  } = useStudio();

  const { alert: alertDialog } = useDialog();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, , onEdgesChange] = useEdgesState<Edge>([]);
  const [isDark, setIsDark] = useState(false);
  const { screenToFlowPosition } = useReactFlow();

  // Load operations when path is selected
  useEffect(() => {
    if (!selectedPathId) {
      setNodes([]);
      return;
    }

    const loadOperations = async () => {
      try {
        const operationsResponse = await getOperationsForPath(selectedPathId);
        const operations = JSON.parse(operationsResponse);

        // Convert operations to nodes
        const operationNodes: Node[] = operations.map((op: any, index: number) => ({
          id: op.id,
          type: 'operation',
          position: { x: 100 + (index * 150), y: 100 },
          data: {
            operation: op.operation,
            color: OPERATION_COLORS[op.operation] || '#64748b',
            dbOperationId: op.id,
          },
        }));

        setNodes(operationNodes);
      } catch (error) {
        console.error('Error loading operations:', error);
      }
    };

    loadOperations();
  }, [selectedPathId, setNodes]);

  // ...existing code...

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

  // Handle node click to show properties
  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (node.type === 'operation') {
        onOperationSelect({
          id: node.data.dbOperationId as string,
          operation: node.data.operation as string,
        });
      }
    },
    [onOperationSelect]
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
      }
    },
    [screenToFlowPosition, setNodes, selectedPathId, alertDialog]
  );

  return (
    <div ref={reactFlowWrapper} className="flex-1 flex flex-col h-full bg-gray-100 dark:bg-gray-900">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
      >
        <Background
          variant={backgroundVariant(gridStyle)}
          gap={gridSize}
          size={1.5}
          color="currentColor"
          style={{
            color: isDark ? 'rgb(148, 163, 184)' : 'rgb(99, 102, 241)',
            opacity: isDark ? 0.3 : 0.2
          }}
        />
        <Controls
          className="bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden"
          style={{
            bottom: 20,
            left: 20,
            right: 'auto',
            top: 'auto',
          }}
        />
      </ReactFlow>
    </div>
  );
}

export default function PathsCanvasView({
  selectedPathId,
  onOperationSelect,
}: {
  selectedPathId: string | null;
  onOperationSelect: (operation: { id: string; operation: string } | null) => void;
}) {
  return (
    <ReactFlowProvider>
      <PathsCanvasInner selectedPathId={selectedPathId} onOperationSelect={onOperationSelect} />
    </ReactFlowProvider>
  );
}

