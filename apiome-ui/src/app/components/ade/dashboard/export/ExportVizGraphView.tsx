'use client';

/**
 * ExportVizGraphView — one paradigm-specific picture of an export (MFX-45.4, #4377).
 *
 * Draws the graph of a graph mode the target declares (`./exportViz.ts`): a protobuf bundle's
 * **import graph** (files, imports; well-known imports external), an RPC export's **service map**
 * (services → methods → request / response messages, streams labelled) or an event export's
 * **channel topology** (AsyncAPI operations → channels → messages; xRegistry message groups → messages
 * → event types). The graph comes from the server, built from the emitted files, so the view has no
 * format knowledge of its own.
 *
 * Each node is a button naming its kind, label and detail in words. A node that stands for a canonical
 * construct selects it — the Review step's own entity selection, so the tree and the code viewer follow —
 * and the step's selection highlights here and is brought into view. A node with no construct (a file,
 * an external message, an event type) is not selectable, and says why.
 */

import { memo, useEffect, useMemo } from 'react';
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Share2 } from 'lucide-react';
import { cn } from '@lib/utils';
import { MOTION_MS, motionDuration } from '@lib/motion';
import {
  nodeKindLabel,
  vizEdgeLabel,
  vizGraphLayout,
  vizNodeAriaLabel,
  vizSelection,
  vizSummary,
  VIZ_GEOMETRY,
  type VizGraph,
  type VizNode,
} from './exportViz';

/** The data one graph node carries. */
interface VizNodeData extends Record<string, unknown> {
  node: VizNode;
  selected: boolean;
  onSelect: (entityKey: string) => void;
}

type VizFlowNode = Node<VizNodeData, 'vizNode'>;

/** One node: its kind, label and detail, as a button that selects its construct. */
export const VizGraphNode = memo(function VizGraphNode({ data }: NodeProps<VizFlowNode>) {
  const { node, selected, onSelect } = data;
  const selectable = Boolean(node.entity_key);
  return (
    <div className="xstd-viz__node-wrap">
      <Handle type="target" position={Position.Left} className="xstd-erd__handle" isConnectable={false} />
      <Handle type="source" position={Position.Right} className="xstd-erd__handle" isConnectable={false} />
      <button
        type="button"
        className="xstd-viz__node nodrag"
        data-kind={node.kind}
        data-external={node.external ? 'true' : 'false'}
        data-selected={selected}
        aria-pressed={selected}
        aria-label={vizNodeAriaLabel(node)}
        data-testid={`viz-node-${node.id}`}
        disabled={!selectable}
        title={selectable ? undefined : 'This node has no source construct to select'}
        onClick={() => node.entity_key && onSelect(node.entity_key)}
      >
        <span className="xstd-viz__kind" aria-hidden>
          {nodeKindLabel(node.kind)}
          {node.external && <span className="xstd-viz__external"> · external</span>}
        </span>
        <span className="xstd-viz__label" aria-hidden>
          {node.label}
        </span>
        {node.detail && (
          <span className="xstd-viz__detail" aria-hidden>
            {node.detail}
          </span>
        )}
      </button>
    </div>
  );
});

const NODE_TYPES = { vizNode: VizGraphNode };

export interface ExportVizGraphViewProps {
  /** The mode's graph (the manifest's `views[mode]`). */
  graph: VizGraph;
  /** The view switch label of the mode, e.g. `Service map` — the drawing's heading. */
  title: string;
  /** The step's selected canonical construct. */
  selectedEntityKey: string | null;
  /** Select a canonical construct. */
  onSelectEntityKey: (entityKey: string) => void;
  className?: string;
}

/** The drawing: heading + summary, and the flow canvas. */
export function ExportVizGraphView(props: ExportVizGraphViewProps) {
  return (
    <ReactFlowProvider>
      <VizCanvas {...props} />
    </ReactFlowProvider>
  );
}

function VizCanvas({ graph, title, selectedEntityKey, onSelectEntityKey, className }: ExportVizGraphViewProps) {
  const placed = useMemo(() => vizGraphLayout(graph), [graph]);
  const selection = useMemo(() => vizSelection(graph, selectedEntityKey), [graph, selectedEntityKey]);
  const focus = useMemo(() => graph.nodes.find((node) => selection.has(node.id))?.id ?? null, [graph, selection]);

  const nodes = useMemo<VizFlowNode[]>(
    () =>
      placed.map(({ node, x, y }) => ({
        id: node.id,
        type: 'vizNode',
        position: { x, y },
        width: VIZ_GEOMETRY.nodeWidth,
        height: VIZ_GEOMETRY.nodeHeight,
        // Known size and handles: the drawing (edges included) is right on the first paint.
        handles: [
          { type: 'target', position: Position.Left, x: 0, y: VIZ_GEOMETRY.nodeHeight / 2, width: 1, height: 1 },
          {
            type: 'source',
            position: Position.Right,
            x: VIZ_GEOMETRY.nodeWidth,
            y: VIZ_GEOMETRY.nodeHeight / 2,
            width: 1,
            height: 1,
          },
        ],
        draggable: false,
        selectable: false,
        data: { node, selected: selection.has(node.id), onSelect: onSelectEntityKey },
      })),
    [placed, selection, onSelectEntityKey],
  );

  const edges = useMemo<Edge[]>(
    () =>
      graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: 'smoothstep',
        label: vizEdgeLabel(edge),
        ariaLabel: `${edge.kind} from ${edge.source} to ${edge.target}`,
        className: cn('xstd-erd__edge', 'xstd-viz__edge'),
        data: { kind: edge.kind },
        selectable: false,
        focusable: false,
      })),
    [graph.edges],
  );

  return (
    <div className={cn('xstd-erd', className)} data-testid={`export-viz-${graph.mode}`}>
      <div className="xstd-erd__bar">
        <span className="xstd-caps">
          <Share2 aria-hidden />
          {title}
        </span>
        <span className="xstd-note" data-testid="export-viz-summary">
          {vizSummary(graph)}
        </span>
      </div>
      <div className="xstd-erd__canvas" role="group" aria-label={title}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          minZoom={0.2}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
          <FocusNode id={focus} />
        </ReactFlow>
      </div>
    </div>
  );
}

/** Bring the selected node into view whenever the selection moves to another node. */
function FocusNode({ id }: { id: string | null }) {
  const flow = useReactFlow();
  useEffect(() => {
    if (!id) return;
    void flow.fitView({ nodes: [{ id }], maxZoom: 1, padding: 0.8, duration: motionDuration(MOTION_MS.slow) });
  }, [flow, id]);
  return null;
}

export default ExportVizGraphView;
