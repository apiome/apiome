/**
 * A jsdom stand-in for `@xyflow/react` that still renders a flow's **custom node components**
 * (MFX-45.3). React Flow measures its nodes with ResizeObserver and lays them out in a canvas jsdom
 * cannot draw; what a test needs is the nodes' own markup and the edges' attributes. Use it as
 *
 *   jest.mock('@xyflow/react', () =>
 *     jest.requireActual<typeof import('./helpers/xyflow-mock')>('./helpers/xyflow-mock').xyflowMock());
 *
 * Each node renders `nodeTypes[node.type]` with its `id` and `data`; each edge renders a
 * `flow-edge-<id>` element carrying its class, label and (as `data-aria-label`) accessible name. `fitViewMock` records the
 * `fitView` calls `useReactFlow()` receives.
 */

import * as React from 'react';
import { jest } from '@jest/globals';

/** Every `useReactFlow().fitView(...)` call, across tests (reset it in a `beforeEach`). */
export const fitViewMock = jest.fn(() => Promise.resolve(true));

interface MockNode {
  id: string;
  type?: string;
  data: Record<string, unknown>;
}

interface MockEdge {
  id: string;
  source: string;
  target: string;
  label?: React.ReactNode;
  ariaLabel?: string;
  className?: string;
}

/** The module factory for `jest.mock('@xyflow/react', …)`. */
export function xyflowMock() {
  const ReactFlow = ({
    nodes,
    edges,
    nodeTypes = {},
    children,
  }: {
    nodes: MockNode[];
    edges: MockEdge[];
    nodeTypes?: Record<string, React.ComponentType<{ id: string; data: Record<string, unknown> }>>;
    children?: React.ReactNode;
  }) =>
    React.createElement(
      'div',
      { 'data-testid': 'flow' },
      ...nodes.map((node) => {
        const Component = node.type ? nodeTypes[node.type] : undefined;
        return React.createElement(
          'div',
          { key: node.id, 'data-testid': `flow-node-${node.id}` },
          Component ? React.createElement(Component, { id: node.id, data: node.data }) : node.id,
        );
      }),
      ...edges.map((edge) =>
        React.createElement(
          'div',
          {
            key: edge.id,
            'data-testid': `flow-edge-${edge.id}`,
            'data-source': edge.source,
            'data-target': edge.target,
            'data-class': edge.className ?? '',
            'data-aria-label': edge.ariaLabel,
          },
          edge.label ?? null,
        ),
      ),
      children,
    );
  return {
    __esModule: true,
    ReactFlow,
    ReactFlowProvider: ({ children }: { children?: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
    useReactFlow: () => ({ fitView: fitViewMock }),
    Handle: () => null,
    Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
    Background: () => null,
    Controls: () => null,
  };
}
