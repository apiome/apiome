'use client';

import React, { useCallback, useEffect, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Node,
  type NodeProps,
  useEdgesState,
  useNodesState,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { GitMerge } from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import {
  buildLayoutedHistoryGraph,
  HISTORY_WINDOW_STEP,
  MAX_HISTORY_GRAPH_NODES,
  expandVersionsForWindow,
  type RevisionNodeData,
  type VersionHistoryVertex,
} from './version-history-dag';

function RevisionHistoryNode({ data, selected }: NodeProps<Node<RevisionNodeData>>) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 shadow-sm min-w-[11rem] max-w-[14rem] transition-colors ${
        selected
          ? 'border-indigo-500 bg-indigo-50 dark:border-indigo-400 dark:bg-indigo-950/50'
          : 'border-gray-300 bg-white dark:border-gray-600 dark:bg-gray-900'
      }`}
    >
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="flex items-start gap-2">
        {data.isMerge ? (
          <GitMerge className="h-4 w-4 shrink-0 text-violet-600 dark:text-violet-400 mt-0.5" aria-hidden />
        ) : (
          <span className="w-4 shrink-0" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <div className="font-mono text-sm font-semibold text-gray-900 dark:text-gray-50 truncate">
            v{data.versionString}
          </div>
          {data.isMerge && (
            <div className="text-[10px] uppercase tracking-wide text-violet-700 dark:text-violet-300 font-medium mt-0.5">
              Merge
            </div>
          )}
          {data.shortMessage ? (
            <div className="text-xs text-gray-600 dark:text-gray-400 truncate mt-0.5" title={data.shortMessage}>
              {data.shortMessage}
            </div>
          ) : null}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

const nodeTypes = { revisionHistory: RevisionHistoryNode };

export type VersionHistoryGraphPanelProps = {
  /** Filtered list (e.g. lifecycle + tag) — same as versions table */
  versions: VersionHistoryVertex[];
  windowSize: number;
  onWindowSizeIncrease: (nextSize: number) => void;
  /** Primary parent → this revision (OpenAPI compare) */
  onCompareToPrimaryParent: (revisionId: string) => void;
  /** Open read-only spec for this revision */
  onViewSpec: (revisionId: string) => void;
};

export default function VersionHistoryGraphPanel({
  versions,
  windowSize,
  onWindowSizeIncrease,
  onCompareToPrimaryParent,
  onViewSpec,
}: VersionHistoryGraphPanelProps) {
  const expanded = useMemo(() => expandVersionsForWindow(versions, windowSize), [versions, windowSize]);

  const { nodes: layoutNodes, edges: layoutEdges } = useMemo(
    () => buildLayoutedHistoryGraph(expanded),
    [expanded]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutEdges);

  useEffect(() => {
    setNodes(layoutNodes);
    setEdges(layoutEdges);
  }, [layoutNodes, layoutEdges, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const e = _ as React.MouseEvent & { metaKey?: boolean; ctrlKey?: boolean };
      if (e.metaKey || e.ctrlKey) {
        onViewSpec(node.id);
        return;
      }
      onCompareToPrimaryParent(node.id);
    },
    [onCompareToPrimaryParent, onViewSpec]
  );

  const atMaxNodes = expanded.length >= MAX_HISTORY_GRAPH_NODES;
  const canLoadMore = windowSize < versions.length && !atMaxNodes;

  if (versions.length === 0) {
    return null;
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center justify-between gap-2 bg-gray-50/80 dark:bg-gray-900/40">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Revision history graph</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            DAG from parent links (solid = primary parent, dashed = merge parent). Older toward the top. Click a node to
            compare with its primary parent; Ctrl/Cmd-click to view spec. Merge revisions show two incoming edges.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canLoadMore ? (
            <Button
              type="button"
              variant="secondary"
              className="text-xs"
              onClick={() => onWindowSizeIncrease(windowSize + HISTORY_WINDOW_STEP)}
            >
              Load older ({windowSize} → {windowSize + HISTORY_WINDOW_STEP})
            </Button>
          ) : null}
          {atMaxNodes && (
            <span className="text-xs text-amber-600 dark:text-amber-400">
              Max render limit reached ({MAX_HISTORY_GRAPH_NODES} nodes)
            </span>
          )}
          <span className="text-xs text-gray-500 dark:text-gray-400">
            Showing {expanded.length} revision{expanded.length !== 1 ? 's' : ''}
            {expanded.length < versions.length ? ` (of ${versions.length} in view)` : ''}
          </span>
        </div>
      </div>
      <div className="w-full h-[min(420px,55vh)] min-h-[280px]">
        {layoutNodes.length === 0 ? (
          <div className="flex items-center justify-center h-full text-sm text-gray-500 dark:text-gray-400 px-4">
            No revisions to graph.
          </div>
        ) : (
          <ReactFlow
            key={`${expanded.map((v) => v.id).join('|')}-${windowSize}`}
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            fitView
            fitViewOptions={{ padding: 0.15, maxZoom: 1.25 }}
            minZoom={0.2}
            maxZoom={1.5}
            proOptions={{ hideAttribution: true }}
            className="bg-slate-50 dark:bg-gray-950"
          >
            <Background variant={BackgroundVariant.Dots} gap={14} size={1} />
            <Controls />
            <MiniMap
              className="!bg-white/90 dark:!bg-gray-900/90"
              maskColor="rgba(0,0,0,0.12)"
              nodeStrokeWidth={2}
            />
          </ReactFlow>
        )}
      </div>
    </div>
  );
}

export { HISTORY_WINDOW_STEP };
