'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Edge,
  type Node,
  type OnEdgesChange,
  type OnNodesChange,
  useEdgesState,
  useNodesState,
  useReactFlow,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Crosshair, Locate } from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import RevisionHistoryNode from './RevisionHistoryNode';
import {
  buildLayoutedHistoryGraph,
  HISTORY_WINDOW_STEP,
  MAX_HISTORY_GRAPH_NODES,
  expandVersionsForWindow,
  filterVersionsBySelectedBranches,
  laneColorForBranchIndex,
  type RevisionNodeData,
  type VersionHistoryBranchMeta,
  type VersionHistoryTag,
  type VersionHistoryVertex,
} from './version-history-dag';

const nodeTypes = { revisionHistory: RevisionHistoryNode };

export type VersionHistoryGraphPanelProps = {
  /** Filtered list (e.g. lifecycle + tag) — same as versions table */
  versions: VersionHistoryVertex[];
  /** Named branches for tips, lane labels, and optional subgraph filter (#744) */
  branches?: VersionHistoryBranchMeta[];
  /** Tags pinned to specific revisions, rendered as pills on the commit nodes. */
  tags?: VersionHistoryTag[];
  windowSize: number;
  onWindowSizeIncrease: (nextSize: number) => void;
  /** Primary parent → this revision (OpenAPI compare) */
  onCompareToPrimaryParent: (revisionId: string) => void;
  /** Open read-only spec for this revision */
  onViewSpec: (revisionId: string) => void;
  /** Create a named branch from this revision (#2571) */
  onBranchFromRevision?: (revisionId: string) => void;
  /** Canvas-only: switch the editor to this revision. When omitted the menu item is hidden. */
  onCheckoutRevision?: (revisionId: string) => void;
  /** Current HEAD revision id — powers the "Center on HEAD" button. */
  headRevisionId?: string | null;
  /** Currently selected revision (canvas pinned / table row) — powers "Center on selected". */
  selectedRevisionId?: string | null;
};

type GraphCanvasProps = {
  nodes: Node<RevisionNodeData>[];
  edges: Edge[];
  keyValue: string;
  onNodesChange: OnNodesChange<Node<RevisionNodeData>>;
  onEdgesChange: OnEdgesChange<Edge>;
  onNodeClick: (e: React.MouseEvent, node: Node) => void;
  headRevisionId?: string | null;
  selectedRevisionId?: string | null;
};

function GraphCanvas({
  nodes,
  edges,
  keyValue,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  headRevisionId,
  selectedRevisionId,
}: GraphCanvasProps) {
  const { setCenter, getNode, fitView } = useReactFlow();

  const centerOn = useCallback(
    (id: string | null | undefined) => {
      if (!id) return;
      const n = getNode(id);
      if (!n) return;
      const width = n.width ?? 200;
      const height = n.height ?? 52;
      setCenter(n.position.x + width / 2, n.position.y + height / 2, { zoom: 1.2, duration: 400 });
    },
    [getNode, setCenter]
  );

  return (
    <>
      <div className="absolute top-2 right-2 z-10 flex gap-1.5">
        <Button
          type="button"
          variant="secondary"
          className="!px-2 !py-1 text-xs"
          title="Fit all revisions in view"
          onClick={() => fitView({ padding: 0.2, maxZoom: 1.35, duration: 400 })}
        >
          <Crosshair className="h-3.5 w-3.5" aria-hidden />
          <span className="ml-1">Fit all</span>
        </Button>
        {headRevisionId ? (
          <Button
            type="button"
            variant="secondary"
            className="!px-2 !py-1 text-xs"
            title="Center on current HEAD revision"
            onClick={() => centerOn(headRevisionId)}
          >
            <Locate className="h-3.5 w-3.5" aria-hidden />
            <span className="ml-1">HEAD</span>
          </Button>
        ) : null}
        {selectedRevisionId && selectedRevisionId !== headRevisionId ? (
          <Button
            type="button"
            variant="secondary"
            className="!px-2 !py-1 text-xs"
            title="Center on selected revision"
            onClick={() => centerOn(selectedRevisionId)}
          >
            <Locate className="h-3.5 w-3.5" aria-hidden />
            <span className="ml-1">Selected</span>
          </Button>
        ) : null}
      </div>
      <ReactFlow
        key={keyValue}
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
        fitViewOptions={{ padding: 0.2, maxZoom: 1.35 }}
        minZoom={0.15}
        maxZoom={1.75}
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
    </>
  );
}

export default function VersionHistoryGraphPanel({
  versions,
  branches = [],
  tags = [],
  windowSize,
  onWindowSizeIncrease,
  onCompareToPrimaryParent,
  onViewSpec,
  onBranchFromRevision,
  onCheckoutRevision,
  headRevisionId,
  selectedRevisionId,
}: VersionHistoryGraphPanelProps) {
  const [selectedBranchIds, setSelectedBranchIds] = useState<string[]>(() => branches.map((b) => b.id));

  const branchFiltered = useMemo(
    () => filterVersionsBySelectedBranches(versions, branches, selectedBranchIds),
    [versions, branches, selectedBranchIds]
  );

  const expanded = useMemo(() => expandVersionsForWindow(branchFiltered, windowSize), [branchFiltered, windowSize]);

  const { nodes: layoutNodes, edges: layoutEdges } = useMemo(
    () =>
      buildLayoutedHistoryGraph(expanded, {
        branches,
        tags,
        onBranchFromRevision,
        onCheckoutRevision,
        onViewSpec,
        onCompareToPrimaryParent,
      }),
    [expanded, branches, tags, onBranchFromRevision, onCheckoutRevision, onViewSpec, onCompareToPrimaryParent]
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
  const canLoadMore = windowSize < branchFiltered.length && !atMaxNodes;
  const selectionBlocksGraph = branches.length > 0 && selectedBranchIds.length === 0;

  const toggleBranch = useCallback((id: string) => {
    setSelectedBranchIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }, []);

  const selectAllBranches = useCallback(() => {
    setSelectedBranchIds(branches.map((b) => b.id));
  }, [branches]);

  if (versions.length === 0) {
    return null;
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center justify-between gap-2 bg-gray-50/80 dark:bg-gray-900/40">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Revision history graph</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            Left-to-right lanes (older → newer). Solid slate edge = primary parent; dashed violet = merge parent. Click a
            node to compare with its primary parent; Ctrl/Cmd-click to view spec. Merge commits use violet styling; branch
            tips show names and an emerald marker.
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
            {expanded.length < branchFiltered.length ? ` (of ${branchFiltered.length} in branch filter)` : ''}
            {branchFiltered.length < versions.length ? ` — ${versions.length} total in table filter` : ''}
          </span>
        </div>
      </div>

      {branches.length > 0 ? (
        <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center gap-2 bg-white dark:bg-gray-800/80">
          <span className="text-xs font-medium text-gray-600 dark:text-gray-300">Lanes</span>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter graph by named branch">
            {branches.map((b, idx) => {
              const on = selectedBranchIds.includes(b.id);
              const color = laneColorForBranchIndex(idx);
              return (
                <button
                  key={b.id}
                  type="button"
                  aria-pressed={on}
                  title={on ? `Hide history for ${b.name}` : `Show history for ${b.name}`}
                  onClick={() => toggleBranch(b.id)}
                  className={`inline-flex items-center gap-1.5 text-xs rounded-full px-2.5 py-1 border transition-colors ${
                    on
                      ? 'border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100 dark:border-emerald-600'
                      : 'border-gray-200 bg-gray-100 text-gray-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-400'
                  }`}
                >
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${color.dot} ${on ? '' : 'opacity-40'}`}
                    aria-hidden
                  />
                  {b.name}
                </button>
              );
            })}
          </div>
          {selectedBranchIds.length < branches.length ? (
            <button type="button" onClick={selectAllBranches} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
              Select all
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="relative w-full h-[min(420px,55vh)] min-h-[280px]">
        {selectionBlocksGraph ? (
          <div className="flex items-center justify-center h-full text-sm text-gray-500 dark:text-gray-400 px-4 text-center">
            Select at least one branch to show the graph, or use &quot;Select all&quot;.
          </div>
        ) : layoutNodes.length === 0 ? (
          <div className="flex items-center justify-center h-full text-sm text-gray-500 dark:text-gray-400 px-4">
            No revisions to graph.
          </div>
        ) : (
          <ReactFlowProvider>
            <GraphCanvas
              nodes={nodes}
              edges={edges}
              keyValue={`${expanded.map((v) => v.id).join('|')}-${windowSize}-${[...selectedBranchIds].sort().join(',')}`}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={onNodeClick}
              headRevisionId={headRevisionId}
              selectedRevisionId={selectedRevisionId}
            />
          </ReactFlowProvider>
        )}
      </div>
    </div>
  );
}

export { HISTORY_WINDOW_STEP };
