'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import { GitBranch, GitMerge } from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import {
  buildLayoutedHistoryGraph,
  HISTORY_WINDOW_STEP,
  MAX_HISTORY_GRAPH_NODES,
  expandVersionsForWindow,
  filterVersionsBySelectedBranches,
  type RevisionNodeData,
  type VersionHistoryBranchMeta,
  type VersionHistoryVertex,
} from './version-history-dag';

function RevisionHistoryNode({ data, selected }: NodeProps<Node<RevisionNodeData>>) {
  const { isMerge, isBranchTip, branchNamesForTip, tipAccentClass, layoutDirection } = data;
  const horizontal = layoutDirection === 'LR';

  const hoverTitle =
    isBranchTip && branchNamesForTip.length > 0
      ? `Branch tip: ${branchNamesForTip.join(', ')}`
      : isMerge
        ? 'Merge revision (two parents)'
        : undefined;

  const leftAccent = isBranchTip && tipAccentClass ? `border-l-4 ${tipAccentClass} pl-2` : '';

  let surface: string;
  if (selected) {
    surface =
      'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-500 dark:border-indigo-400 dark:bg-indigo-950/50 dark:ring-indigo-400';
  } else if (isMerge) {
    surface =
      'border-2 border-violet-400 bg-violet-50/90 dark:border-violet-500 dark:bg-violet-950/40' +
      (isBranchTip ? ' ring-2 ring-emerald-500/70 dark:ring-emerald-500/60' : '');
  } else if (isBranchTip) {
    surface =
      'border border-emerald-600/40 bg-white ring-2 ring-emerald-500/75 dark:border-emerald-500/50 dark:bg-gray-900 dark:ring-emerald-500/70';
  } else {
    surface = 'border-gray-300 bg-white dark:border-gray-600 dark:bg-gray-900';
  }

  return (
    <div title={hoverTitle} className={`rounded-lg border px-3 py-2 shadow-sm min-w-[11rem] max-w-[14rem] transition-colors ${surface} ${leftAccent}`.trim()}>
      {horizontal ? (
        <>
          <Handle type="target" position={Position.Left} className="opacity-0" />
          <Handle type="source" position={Position.Right} className="opacity-0" />
        </>
      ) : (
        <>
          <Handle type="target" position={Position.Top} className="opacity-0" />
          <Handle type="source" position={Position.Bottom} className="opacity-0" />
        </>
      )}
      <div className="flex items-start gap-2">
        <div className="flex flex-col gap-0.5 shrink-0 mt-0.5" aria-hidden>
          {isMerge ? <GitMerge className="h-4 w-4 text-violet-600 dark:text-violet-400" /> : <span className="h-4 w-4 block" />}
          {isBranchTip ? <GitBranch className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> : null}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-mono text-sm font-semibold text-gray-900 dark:text-gray-50 truncate">
            v{data.versionString}
          </div>
          {isMerge ? (
            <div className="text-[10px] uppercase tracking-wide text-violet-800 dark:text-violet-200 font-semibold mt-0.5">
              Merge commit
            </div>
          ) : null}
          {isBranchTip && branchNamesForTip.length > 0 ? (
            <div className="text-[10px] font-medium text-emerald-800 dark:text-emerald-200 mt-0.5 truncate" title={branchNamesForTip.join(', ')}>
              Tip: {branchNamesForTip.join(', ')}
            </div>
          ) : null}
          {data.shortMessage ? (
            <div className="text-xs text-gray-600 dark:text-gray-400 truncate mt-0.5" title={data.shortMessage}>
              {data.shortMessage}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

const nodeTypes = { revisionHistory: RevisionHistoryNode };

export type VersionHistoryGraphPanelProps = {
  /** Filtered list (e.g. lifecycle + tag) — same as versions table */
  versions: VersionHistoryVertex[];
  /** Named branches for tips, lane labels, and optional subgraph filter (#744) */
  branches?: VersionHistoryBranchMeta[];
  windowSize: number;
  onWindowSizeIncrease: (nextSize: number) => void;
  /** Primary parent → this revision (OpenAPI compare) */
  onCompareToPrimaryParent: (revisionId: string) => void;
  /** Open read-only spec for this revision */
  onViewSpec: (revisionId: string) => void;
};

export default function VersionHistoryGraphPanel({
  versions,
  branches = [],
  windowSize,
  onWindowSizeIncrease,
  onCompareToPrimaryParent,
  onViewSpec,
}: VersionHistoryGraphPanelProps) {
  const [selectedBranchIds, setSelectedBranchIds] = useState<string[]>(() => branches.map((b) => b.id));

  const branchFiltered = useMemo(
    () => filterVersionsBySelectedBranches(versions, branches, selectedBranchIds),
    [versions, branches, selectedBranchIds]
  );

  const expanded = useMemo(() => expandVersionsForWindow(branchFiltered, windowSize), [branchFiltered, windowSize]);

  const { nodes: layoutNodes, edges: layoutEdges } = useMemo(
    () => buildLayoutedHistoryGraph(expanded, { branches }),
    [expanded, branches]
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
          <span className="text-xs font-medium text-gray-600 dark:text-gray-300">Branches</span>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter graph by named branch">
            {branches.map((b) => {
              const on = selectedBranchIds.includes(b.id);
              return (
                <button
                  key={b.id}
                  type="button"
                  title={on ? `Hide history for ${b.name}` : `Show history for ${b.name}`}
                  onClick={() => toggleBranch(b.id)}
                  className={`text-xs rounded-full px-2.5 py-1 border transition-colors ${
                    on
                      ? 'border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100 dark:border-emerald-600'
                      : 'border-gray-200 bg-gray-100 text-gray-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-400'
                  }`}
                >
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

      <div className="w-full h-[min(420px,55vh)] min-h-[280px]">
        {selectionBlocksGraph ? (
          <div className="flex items-center justify-center h-full text-sm text-gray-500 dark:text-gray-400 px-4 text-center">
            Select at least one branch to show the graph, or use &quot;Select all&quot;.
          </div>
        ) : layoutNodes.length === 0 ? (
          <div className="flex items-center justify-center h-full text-sm text-gray-500 dark:text-gray-400 px-4">
            No revisions to graph.
          </div>
        ) : (
          <ReactFlow
            key={`${expanded.map((v) => v.id).join('|')}-${windowSize}-${[...selectedBranchIds].sort().join(',')}`}
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
        )}
      </div>
    </div>
  );
}

export { HISTORY_WINDOW_STEP };
