'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  buildBrowseSpecSchemaGraph,
  BROWSE_LAYOUT_DENSITY_LABELS,
  BROWSE_LAYOUT_DIRECTION_LABELS,
  layoutSpecSchemaNodes,
  type BrowseGraphFormat,
  type BrowseLayoutDensity,
  type BrowseLayoutDirection,
  type BrowseLayoutOptions,
} from './spec-schema-graph';

export interface SpecVisualCanvasProps {
  spec: unknown;
  format: BrowseGraphFormat;
  isDark: boolean;
}

function SchemaNode({ data }: NodeProps) {
  const d = data as { label: string; subtitle?: string; mono?: boolean };
  return (
    <div className="min-w-[180px] max-w-[280px] rounded-lg border border-border-strong bg-surface px-3 py-2.5 shadow-sm">
      <Handle
        type="target"
        position={Position.Top}
        className="!size-2 !border !border-border-strong !bg-inset"
      />
      <div
        className={`break-words text-sm font-semibold text-fg ${
          d.mono ? 'font-mono' : ''
        }`}
      >
        {d.label}
      </div>
      {d.subtitle && d.subtitle !== d.label && (
        <div className="mt-0.5 line-clamp-3 text-2xs leading-snug text-fg-muted">
          {d.subtitle}
        </div>
      )}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!size-2 !border !border-border-strong !bg-inset"
      />
    </div>
  );
}

const nodeTypes = { specSchema: SchemaNode } satisfies NodeTypes;

function LegendSwatch({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <span
      className="inline-block w-7 align-middle"
      style={{
        borderBottom: `3px ${dashed ? 'dashed' : 'solid'} ${color}`,
      }}
    />
  );
}

const LAYOUT_DIRECTIONS: BrowseLayoutDirection[] = ['auto', 'TB', 'BT', 'LR', 'RL'];
const LAYOUT_DENSITIES: BrowseLayoutDensity[] = ['compact', 'default', 'spacious'];

function FlowInner({ spec, format, isDark }: SpecVisualCanvasProps) {
  const { fitView } = useReactFlow();
  const [layoutDirection, setLayoutDirection] = useState<BrowseLayoutDirection>('auto');
  const [layoutDensity, setLayoutDensity] = useState<BrowseLayoutDensity>('default');
  const layoutOptions = useMemo(
    (): BrowseLayoutOptions => ({ direction: layoutDirection, density: layoutDensity }),
    [layoutDirection, layoutDensity]
  );

  const graph = useMemo(
    () => buildBrowseSpecSchemaGraph(spec, format, isDark, layoutOptions),
    [spec, format, isDark, layoutOptions]
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(graph.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(graph.edges);

  useEffect(() => {
    setNodes(graph.nodes);
    setEdges(graph.edges);
  }, [graph, setNodes, setEdges]);

  useEffect(() => {
    if (graph.nodes.length === 0) return;
    const id = requestAnimationFrame(() => {
      fitView({ padding: 0.14, duration: 280 });
    });
    return () => cancelAnimationFrame(id);
  }, [spec, format, isDark, layoutDirection, layoutDensity, graph.nodes.length, graph.edges.length, fitView]);

  const runAutoLayout = useCallback(() => {
    const next = layoutSpecSchemaNodes(graph.nodes, graph.edges, layoutOptions);
    setNodes(next);
    requestAnimationFrame(() => {
      fitView({ padding: 0.12, maxZoom: 1.2, duration: 320 });
    });
  }, [graph.nodes, graph.edges, layoutOptions, setNodes, fitView]);

  if (graph.unavailableReason) {
    return (
      <div className="flex min-h-[560px] flex-col items-center justify-center rounded-lg border border-border bg-subtle/80 px-6 py-16 text-center">
        <p className="max-w-md text-sm leading-relaxed text-fg-muted">{graph.unavailableReason}</p>
      </div>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <div className="flex min-h-[560px] flex-col items-center justify-center rounded-lg border border-border bg-subtle/80 px-6 py-16 text-center">
        <p className="max-w-md text-sm leading-relaxed text-fg-muted">
          {graph.unavailableReason ?? 'No schema shapes or local references to draw.'}
        </p>
      </div>
    );
  }

  const legendStroke = {
    allOf: isDark ? '#60a5fa' : '#2563eb',
    anyOf: isDark ? '#fb923c' : '#ea580c',
    oneOf: isDark ? '#c084fc' : '#9333ea',
    ref: isDark ? '#94a3b8' : '#64748b',
  };

  return (
    <div className="h-[min(70vh,640px)] min-h-[520px] w-full overflow-hidden rounded-lg border border-border bg-subtle">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        panOnScroll
        zoomOnScroll
        zoomOnPinch
        minZoom={0.06}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
        fitView
      >
        <Background
          id="browse-spec-visual-bg"
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          className="!bg-subtle"
          color={isDark ? '#3f3f46' : '#d4d4d8'}
        />
        <Controls
          showInteractive={false}
          className="!m-3 !overflow-hidden !rounded-lg !border !border-border !bg-surface !shadow-sm"
        />
        <MiniMap
          className="!m-3 !overflow-hidden !rounded-lg !border !border-border"
          pannable
          zoomable
          maskColor={isDark ? 'rgba(24,24,27,0.88)' : 'rgba(244,244,245,0.9)'}
          nodeColor={() => (isDark ? '#52525b' : '#a1a1aa')}
        />
        <Panel
          position="top-left"
          className="m-3 max-w-[min(100%,380px)] rounded-lg border border-border bg-surface/95 px-3 py-2 text-2xs text-fg-muted shadow-sm backdrop-blur-sm"
        >
          <div className="font-semibold text-fg">Relationships</div>
          <p className="mt-1 leading-snug">
            Drag nodes, pan and zoom. Edge labels show{' '}
            <code className="rounded-xs bg-subtle px-1 py-px font-mono text-2xs">allOf</code>,{' '}
            <code className="rounded-xs bg-subtle px-1 py-px font-mono text-2xs">anyOf</code>,{' '}
            <code className="rounded-xs bg-subtle px-1 py-px font-mono text-2xs">oneOf</code>, or
            property paths for <code className="rounded-xs bg-subtle px-1 py-px font-mono text-2xs">$ref</code>.
          </p>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
            <li className="flex items-center gap-1.5">
              <LegendSwatch color={legendStroke.allOf} />
              <span>allOf</span>
            </li>
            <li className="flex items-center gap-1.5">
              <LegendSwatch color={legendStroke.anyOf} dashed />
              <span>anyOf</span>
            </li>
            <li className="flex items-center gap-1.5">
              <LegendSwatch color={legendStroke.oneOf} dashed />
              <span>oneOf</span>
            </li>
            <li className="flex items-center gap-1.5">
              <LegendSwatch color={legendStroke.ref} />
              <span>$ref</span>
            </li>
          </ul>
          <p className="mt-2 border-t border-border pt-2 leading-snug">
            Clusters are packed into rows. Adjust <span className="font-semibold">flow</span> and{' '}
            <span className="font-semibold">spacing</span> (top right) for readability, then{' '}
            <span className="font-semibold">Auto-layout</span> to refit the view after dragging nodes.
          </p>
        </Panel>
        <Panel
          position="top-right"
          className="m-3 flex max-w-[200px] flex-col gap-2 rounded-lg border border-border bg-surface/95 p-2 shadow-sm backdrop-blur-sm"
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="browse-visual-flow" className="text-2xs font-semibold uppercase tracking-wide text-fg-muted">
              Flow
            </label>
            <select
              id="browse-visual-flow"
              value={layoutDirection}
              onChange={(e) => setLayoutDirection(e.target.value as BrowseLayoutDirection)}
              className="control control-sm font-medium"
            >
              {LAYOUT_DIRECTIONS.map((d) => (
                <option key={d} value={d}>
                  {BROWSE_LAYOUT_DIRECTION_LABELS[d]}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="browse-visual-density" className="text-2xs font-semibold uppercase tracking-wide text-fg-muted">
              Spacing
            </label>
            <select
              id="browse-visual-density"
              value={layoutDensity}
              onChange={(e) => setLayoutDensity(e.target.value as BrowseLayoutDensity)}
              className="control control-sm font-medium"
            >
              {LAYOUT_DENSITIES.map((d) => (
                <option key={d} value={d}>
                  {BROWSE_LAYOUT_DENSITY_LABELS[d]}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={runAutoLayout}
            className="rounded-md bg-subtle px-3 py-1.5 text-2xs font-semibold text-fg transition-colors hover:bg-inset"
            title="Re-run layout with the current flow and spacing, then zoom to fit"
          >
            Auto-layout
          </button>
        </Panel>
      </ReactFlow>
    </div>
  );
}

export function SpecVisualCanvas(props: SpecVisualCanvasProps) {
  return (
    <ReactFlowProvider>
      <FlowInner {...props} />
    </ReactFlowProvider>
  );
}
