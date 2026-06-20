/**
 * React Flow workflow canvas for static mockup (ESM + htm).
 * Loaded from workflow-canvas.html via <script type="module" src="workflow-app.js"></script>
 */
import React, { useCallback, useMemo } from 'https://esm.sh/react@18.3.1';
import { createRoot } from 'https://esm.sh/react-dom@18.3.1/client';
import htm from 'https://esm.sh/htm@3.1.1';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  useNodesState,
  useEdgesState,
  addEdge,
} from 'https://esm.sh/@xyflow/react@12.10.2?deps=react@18.3.1,react-dom@18.3.1';

const html = htm.bind(React.createElement);

const initialNodes = [
  {
    id: 'n1',
    position: { x: 0, y: 70 },
    data: { label: 'Data change\n(import / CRUD outbox)' },
    style: {
      width: 200,
      fontSize: 12,
      borderRadius: 12,
      border: '1px solid rgba(139,92,246,0.55)',
      background: 'rgba(139,92,246,0.08)',
    },
  },
  {
    id: 'n2',
    position: { x: 250, y: 70 },
    data: { label: 'Rule engine\n(bundle v12 · signed)' },
    style: {
      width: 200,
      fontSize: 12,
      borderRadius: 12,
      border: '1px solid rgba(59,130,246,0.45)',
      background: 'rgba(59,130,246,0.08)',
    },
  },
  {
    id: 'n3',
    position: { x: 500, y: 60 },
    data: { label: 'Match?\n(predicate + projection)' },
    style: {
      width: 180,
      height: 100,
      fontSize: 12,
      borderRadius: 8,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      border: '2px dashed rgba(234,179,8,0.75)',
      background: 'rgba(234,179,8,0.06)',
    },
  },
  {
    id: 'n4',
    position: { x: 380, y: 210 },
    data: { label: 'Pre-action\n(audit · freeze · validate)' },
    style: {
      width: 200,
      fontSize: 12,
      borderRadius: 12,
      border: '1px solid rgba(16,185,129,0.45)',
      background: 'rgba(16,185,129,0.08)',
    },
  },
  {
    id: 'n5',
    position: { x: 380, y: 340 },
    data: { label: 'Parallel fan-out\n(concurrency pool)' },
    style: {
      width: 200,
      fontSize: 12,
      borderRadius: 12,
      border: '1px solid rgba(236,72,153,0.45)',
      background: 'rgba(236,72,153,0.08)',
    },
  },
  {
    id: 'n6a',
    position: { x: 100, y: 480 },
    data: { label: 'Catalog A' },
    style: { width: 140, fontSize: 11, borderRadius: 10 },
  },
  {
    id: 'n6b',
    position: { x: 310, y: 480 },
    data: { label: 'Python script\n(sandboxed)' },
    style: {
      width: 150,
      fontSize: 11,
      borderRadius: 10,
      border: '1px solid rgba(139,92,246,0.4)',
    },
  },
  {
    id: 'n6c',
    position: { x: 520, y: 480 },
    data: { label: 'Catalog B' },
    style: { width: 140, fontSize: 11, borderRadius: 10 },
  },
  {
    id: 'n7',
    position: { x: 380, y: 600 },
    data: { label: 'Join outcomes\n(ALL / ANY / adaptive)' },
    style: {
      width: 200,
      fontSize: 12,
      borderRadius: 12,
      border: '1px solid rgba(100,116,139,0.5)',
      background: 'rgba(100,116,139,0.06)',
    },
  },
  {
    id: 'n8',
    position: { x: 180, y: 730 },
    data: { label: 'On success\n(follow-up chain)' },
    style: {
      width: 180,
      fontSize: 12,
      borderRadius: 12,
      border: '1px solid rgba(34,197,94,0.5)',
      background: 'rgba(34,197,94,0.06)',
    },
  },
  {
    id: 'n9',
    position: { x: 500, y: 730 },
    data: { label: 'On failure\n(compensation · ticket)' },
    style: {
      width: 200,
      fontSize: 12,
      borderRadius: 12,
      border: '1px solid rgba(239,68,68,0.5)',
      background: 'rgba(239,68,68,0.06)',
    },
  },
  {
    id: 'n10',
    position: { x: 340, y: 870 },
    data: { label: 'Immutable audit ledger\n(hash-chained)' },
    style: {
      width: 280,
      fontSize: 12,
      borderRadius: 12,
      fontWeight: 600,
      border: '1px solid rgba(59,130,246,0.35)',
      background: 'rgba(59,130,246,0.05)',
    },
  },
];

const initialEdges = [
  { id: 'e1-2', source: 'n1', target: 'n2', animated: true, markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e2-3', source: 'n2', target: 'n3', markerEnd: { type: MarkerType.ArrowClosed } },
  {
    id: 'e3-4',
    source: 'n3',
    target: 'n4',
    label: 'yes',
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: 'rgb(34 197 94)' },
  },
  { id: 'e4-5', source: 'n4', target: 'n5', markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e5-6a', source: 'n5', target: 'n6a', markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e5-6b', source: 'n5', target: 'n6b', markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e5-6c', source: 'n5', target: 'n6c', markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e6a-7', source: 'n6a', target: 'n7', markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e6b-7', source: 'n6b', target: 'n7', markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e6c-7', source: 'n6c', target: 'n7', markerEnd: { type: MarkerType.ArrowClosed } },
  {
    id: 'e7-8',
    source: 'n7',
    target: 'n8',
    label: 'success / partial',
    style: { stroke: 'rgb(34 197 94)' },
    markerEnd: { type: MarkerType.ArrowClosed },
  },
  {
    id: 'e7-9',
    source: 'n7',
    target: 'n9',
    label: 'failure',
    style: { stroke: 'rgb(239 68 68)' },
    markerEnd: { type: MarkerType.ArrowClosed },
  },
  { id: 'e8-10', source: 'n8', target: 'n10', markerEnd: { type: MarkerType.ArrowClosed } },
  { id: 'e9-10', source: 'n9', target: 'n10', markerEnd: { type: MarkerType.ArrowClosed } },
];

function FlowInner() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const onConnect = useCallback(
    (p) => setEdges((eds) => addEdge({ ...p, animated: true }, eds)),
    [setEdges],
  );
  const defaultEdgeOptions = useMemo(
    () => ({ style: { strokeWidth: 1.5, stroke: 'rgb(113 113 122)' } }),
    [],
  );
  return html`
    <${ReactFlow}
      nodes=${nodes}
      edges=${edges}
      onNodesChange=${onNodesChange}
      onEdgesChange=${onEdgesChange}
      onConnect=${onConnect}
      fitView=${true}
      fitViewOptions=${{ padding: 0.2 }}
      defaultEdgeOptions=${defaultEdgeOptions}
      proOptions=${{ hideAttribution: true }}
      className="text-gray-900 dark:text-gray-100"
    >
      <${MiniMap}
        zoomable=${true}
        pannable=${true}
        className="!rounded-lg !border !border-gray-200 !bg-white/90 dark:!border-gray-700 dark:!bg-gray-900/90"
      />
      <${Controls} className="!rounded-lg !border !border-gray-200 !shadow-md dark:!border-gray-700" />
      <${Background} gap=${20} size=${1} color="rgba(148,163,184,0.35)" />
    </${ReactFlow}>
  `;
}

function App() {
  return html`<${ReactFlowProvider}><${FlowInner} /></${ReactFlowProvider}>`;
}

const rootEl = document.getElementById('flow-root');
if (rootEl) {
  createRoot(rootEl).render(html`<${App} />`);
}
