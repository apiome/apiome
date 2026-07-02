'use client';

import React, { useMemo, useEffect } from 'react';
import {
  ReactFlow,
  useNodesState,
  useEdgesState,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/Dialog';
import { buildRelationshipGraphData, type ClassWithProperties } from '@/app/utils/relationship-graph';
import { applyAutoLayout } from '@/app/utils/canvas-auto-layout';

const NODE_WIDTH = 140;
const NODE_HEIGHT = 40;

interface RelationshipGraphDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  version: { id: string; version_id: string } | null;
  projectName: string;
  /** Classes with properties for the selected version; loaded when user opens the graph */
  classesWithProperties: ClassWithProperties[] | null;
  isLoading?: boolean;
}

export default function RelationshipGraphDialog({
  open,
  onOpenChange,
  version,
  projectName,
  classesWithProperties,
  isLoading = false,
}: RelationshipGraphDialogProps) {
  const graphData = useMemo(
    () => (classesWithProperties?.length ? buildRelationshipGraphData(classesWithProperties) : { nodes: [], edges: [] }),
    [classesWithProperties]
  );

  const { initialNodes, initialEdges } = useMemo(() => {
    if (graphData.nodes.length === 0) {
      return { initialNodes: [], initialEdges: [] };
    }
    const rfNodes: Node[] = graphData.nodes.map((n) => ({
      id: n.id,
      type: 'default',
      position: { x: 0, y: 0 },
      data: { label: n.name },
      measured: { width: NODE_WIDTH, height: NODE_HEIGHT },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    }));
    const rfEdges: Edge[] = graphData.edges.map((e, i) => ({
      id: `e-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
    }));
    const laidOut = applyAutoLayout(rfNodes, rfEdges, {
      direction: 'TB',
      nodeSpacingX: 60,
      nodeSpacingY: 80,
      padding: 40,
      minimizeCrossings: true,
    });
    return { initialNodes: laidOut, initialEdges: rfEdges };
  }, [graphData]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  const empty = !classesWithProperties?.length || graphData.nodes.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            Relationship graph
            {version && (
              <span className="text-sm font-normal text-gray-500 dark:text-gray-400 ml-2">
                {projectName} — v{version.version_id}
              </span>
            )}
          </DialogTitle>
        </DialogHeader>
        <div className="flex-1 min-h-[280px] flex flex-col rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          {isLoading ? (
            <div className="flex-1 min-h-[280px] flex items-center justify-center text-gray-500 dark:text-gray-400">
              Loading schema…
            </div>
          ) : empty ? (
            <div className="flex-1 min-h-[280px] flex flex-col items-center justify-center gap-2 px-6 py-8 text-center">
              <p className="text-gray-600 dark:text-gray-400 font-medium">
                {classesWithProperties === null
                  ? 'No schema data loaded.'
                  : 'This version has no classes yet.'}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-500 max-w-sm">
                Add classes in the Studio and use reference properties ($ref) to other classes to see a relationship graph here.
              </p>
            </div>
          ) : (
            <div className="flex-1 min-h-[400px] w-full flex flex-col">
              {graphData.edges.length === 0 && graphData.nodes.length > 0 && (
                <div className="flex-shrink-0 px-3 py-2 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200/80 dark:border-amber-800/50 text-sm text-amber-800 dark:text-amber-200">
                  This version has {graphData.nodes.length} class{graphData.nodes.length !== 1 ? 'es' : ''} but no references ($ref) between them. Add reference properties in the Studio to see relationships here.
                </div>
              )}
              <div className="w-full" style={{ height: '420px', minHeight: '420px' }}>
              <ReactFlow
                key={version?.id ?? 'graph'}
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={true}
                fitView
                fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                className="bg-gray-50 dark:bg-gray-900"
              >
                <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
                <Controls />
                <MiniMap />
              </ReactFlow>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
