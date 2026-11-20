'use client';

/**
 * Arazzo step graph (COA-1.3, #7039).
 *
 * Draws one workflow's steps and their success/failure routing as a deterministic SVG — the
 * dependency graph's approach (`DependencyGraphSvg`): positions come from the pure
 * `layoutStepGraph`, the drawing scales with its `viewBox`, and in-graph text uses the
 * `SVG_TEXT_SIZE` vocabulary. It is a picture of the step list beside it, which stays the
 * source of truth.
 *
 * Keyboard: every step node is a focusable `role="button"`, so Tab reaches it and Enter / Space
 * opens the step drawer, the same as clicking; a called-workflow node selects that workflow.
 * The edges carry no colour-only meaning — each is labelled, failure edges are dashed and retry
 * edges dotted — and a visually hidden list repeats the routing for screen readers.
 */

import React, { useMemo } from 'react';
import { SVG_TEXT_SIZE } from '@/app/components/ui/svgTypography';
import {
  buildStepGraph,
  describeStepGraph,
  fitStepLabel,
  layoutStepGraph,
  type StepGraphEdgeKind,
  type StepGraphNodeBox,
} from './arazzoStepGraphModel';
import type { ArazzoWorkflowView } from './arazzoWorkflowModel';

const EDGE_KINDS: StepGraphEdgeKind[] = ['next', 'success', 'failure', 'retry'];

export interface ArazzoStepGraphProps {
  /** The workflow to draw. */
  workflow: ArazzoWorkflowView;
  /** Open the step drawer for a step. */
  onOpenStep: (stepId: string) => void;
  /** Select another workflow (a `goto` / called-workflow target). */
  onOpenWorkflow: (workflowId: string) => void;
}

/** The accessible name of an actionable node. */
function nodeActionLabel(node: StepGraphNodeBox): string | null {
  if (node.kind === 'step') return `Step ${node.label}: ${node.detail ?? 'no target'}. Open step details`;
  if (node.kind === 'workflow') return `Workflow ${node.label}. Show this workflow`;
  return null;
}

/**
 * One node: a box (or a pill for the terminals) with its label, target line and retry badge.
 *
 * @param props The placed node and its activation handler (`null` for a terminal).
 * @returns The node's SVG group.
 */
function GraphNode({ node, onActivate }: { node: StepGraphNodeBox; onActivate: (() => void) | null }) {
  const terminal = node.kind === 'start' || node.kind === 'end' || node.kind === 'failed';
  const label = nodeActionLabel(node);
  const centreX = node.x + node.width / 2;
  const interactive = onActivate
    ? {
        role: 'button',
        tabIndex: 0,
        'aria-label': label ?? node.label,
        onClick: onActivate,
        onKeyDown: (event: React.KeyboardEvent<SVGGElement>) => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          onActivate();
        },
      }
    : { 'aria-hidden': true as const };

  return (
    <g
      className="awf-graph__node"
      data-kind={node.kind}
      data-unresolved={node.unresolved ? 'true' : undefined}
      data-testid={node.stepId ? `awf-graph-node-${node.stepId}` : `awf-graph-node-${node.kind}`}
      {...interactive}
    >
      <title>{[node.label, node.detail, node.retryLabel].filter(Boolean).join(' — ')}</title>
      <rect
        className="awf-graph__box"
        x={node.x}
        y={node.y}
        width={node.width}
        height={node.height}
        rx={terminal ? node.height / 2 : 8}
      />
      {terminal ? (
        <text className="awf-graph__label" x={centreX} y={node.y + node.height / 2} dy="0.35em" textAnchor="middle" fontSize={SVG_TEXT_SIZE.body}>
          {node.label}
        </text>
      ) : (
        <>
          <text className="awf-graph__label" x={node.x + 12} y={node.y + 22} fontSize={SVG_TEXT_SIZE.body}>
            {fitStepLabel(node.label)}
          </text>
          {node.detail ? (
            <text className="awf-graph__detail" x={node.x + 12} y={node.y + 40} fontSize={SVG_TEXT_SIZE.label}>
              {fitStepLabel(node.detail, 30)}
            </text>
          ) : null}
          {node.retryLabel ? (
            <text
              className="awf-graph__retry"
              x={node.x + node.width - 10}
              y={node.y + 22}
              textAnchor="end"
              fontSize={SVG_TEXT_SIZE.tick}
            >
              {node.retryLabel}
            </text>
          ) : null}
        </>
      )}
    </g>
  );
}

/**
 * The step graph for one workflow.
 *
 * @param props See {@link ArazzoStepGraphProps}.
 * @returns The labelled SVG, its legend and its text equivalent.
 */
export default function ArazzoStepGraph({ workflow, onOpenStep, onOpenWorkflow }: ArazzoStepGraphProps) {
  const graph = useMemo(() => buildStepGraph(workflow), [workflow]);
  const layout = useMemo(() => layoutStepGraph(graph), [graph]);
  const description = useMemo(() => describeStepGraph(graph), [graph]);
  // Marker ids must be unique per document; two workflows' graphs never share one.
  const markerPrefix = `awf-arrow-${workflow.workflowId.replace(/[^A-Za-z0-9_-]/g, '_')}`;

  return (
    <figure className="awf-graph" data-testid="awf-step-graph">
      <div className="awf-graph__canvas">
        <svg
          className="awf-graph__svg"
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width={layout.width}
          preserveAspectRatio="xMinYMin meet"
          role="group"
          aria-label={`Step graph for workflow ${workflow.workflowId}: ${workflow.steps.length} step${workflow.steps.length === 1 ? '' : 's'}`}
        >
          <defs>
            {EDGE_KINDS.map((kind) => (
              <marker
                key={kind}
                id={`${markerPrefix}-${kind}`}
                className={`awf-graph__arrow awf-graph__arrow--${kind}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
            ))}
          </defs>
          <g aria-hidden>
            {layout.edges.map((edge) => (
              <path
                key={edge.id}
                className={`awf-graph__edge awf-graph__edge--${edge.kind}`}
                d={edge.d}
                markerEnd={`url(#${markerPrefix}-${edge.kind})`}
              />
            ))}
            {layout.edges.map((edge) => {
              const width = Math.max(28, edge.label.length * 6 + 10);
              return (
                <g key={`${edge.id}-label`} className="awf-graph__edge-label" data-kind={edge.kind}>
                  <rect x={edge.labelX - width / 2} y={edge.labelY - 8} width={width} height={16} rx={4} />
                  <text x={edge.labelX} y={edge.labelY} dy="0.35em" textAnchor="middle" fontSize={SVG_TEXT_SIZE.tick}>
                    {edge.label}
                  </text>
                </g>
              );
            })}
          </g>
          {layout.nodes.map((node) => {
            const stepId = node.stepId;
            const workflowId = node.workflowId;
            const onActivate =
              node.kind === 'step' && stepId
                ? () => onOpenStep(stepId)
                : node.kind === 'workflow' && workflowId
                  ? () => onOpenWorkflow(workflowId)
                  : null;
            return <GraphNode key={node.id} node={node} onActivate={onActivate} />;
          })}
        </svg>
      </div>
      <ul className="sr-only" aria-label={`Routing of workflow ${workflow.workflowId}`}>
        {description.map((line, index) => (
          <li key={`${index}-${line}`}>{line}</li>
        ))}
      </ul>
      <ul className="awf-graph__legend" aria-label="Edge types">
        <li data-kind="next">Next step</li>
        <li data-kind="success">On success</li>
        <li data-kind="failure">On failure</li>
        <li data-kind="retry">Retry</li>
      </ul>
    </figure>
  );
}
