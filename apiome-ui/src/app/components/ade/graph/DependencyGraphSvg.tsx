'use client';

/**
 * The bounded dependency-graph drawing (CDG-3.4, #5969) — the sunset timeline's SVG approach.
 *
 * A picture of the list beside it, which stays the source of truth: every fact here is also in the
 * list, in words. Each node is a link (its page, or the graph page centred on it); a depth-1 node
 * has a separate expand button that draws its own neighbours one column further out. Stale edges
 * are dashed and their nodes dimmed and labelled "(stale)"; the kind is a letter inside the node,
 * so colour is never the only signal. A column that has more nodes than it draws says how many.
 */

import * as React from 'react';
import Link from 'next/link';
import { SVG_TEXT_SIZE } from '@/app/components/ui/svgTypography';
import { NODE_RADIUS, graphAriaLabel, type GraphLayout, type GraphLayoutNode } from './graphLayoutModel';

export interface DependencyGraphSvgProps {
  layout: GraphLayout;
  /** Expand or collapse a depth-1 node. */
  onToggle?: (node: GraphLayoutNode) => void;
  /** Node ids whose neighbours are loading. */
  loadingIds?: ReadonlySet<string>;
}

export function DependencyGraphSvg({ layout, onToggle, loadingIds }: DependencyGraphSvgProps) {
  const handleKeyDown = (event: React.KeyboardEvent<SVGGElement>, node: GraphLayoutNode) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    onToggle?.(node);
  };

  return (
    <div className="dg-plot" data-testid="dependency-graph-plot">
      <svg
        className="dg-svg"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        preserveAspectRatio="xMidYMin meet"
        role="group"
        aria-label={graphAriaLabel(layout)}
      >
        <g aria-hidden>
          {layout.links.map((link) => (
            <line
              key={link.key}
              className="dg-link"
              data-provenance={link.provenance}
              data-stale={link.stale ? '' : undefined}
              x1={link.x1}
              y1={link.y1}
              x2={link.x2}
              y2={link.y2}
            />
          ))}
        </g>
        {layout.nodes.map((node) => (
          <g
            key={node.key}
            className="dg-node"
            data-kind={node.kind}
            data-column={node.column}
            data-stale={node.stale ? '' : undefined}
            data-testid={`graph-node-${node.id}`}
          >
            <Link href={node.href} aria-label={node.ariaLabel} className="dg-node__link">
              <title>{node.ariaLabel}</title>
              <circle className="dg-node__ring" cx={node.x} cy={node.y} r={NODE_RADIUS + 5} />
              <circle className="dg-node__disc" cx={node.x} cy={node.y} r={NODE_RADIUS} />
              <text
                className="dg-node__kind"
                x={node.x}
                y={node.y}
                dy="0.35em"
                textAnchor="middle"
                fontSize={SVG_TEXT_SIZE.value}
                aria-hidden
              >
                {node.abbreviation}
              </text>
              <text
                className="dg-node__caption"
                x={node.x}
                y={node.y + NODE_RADIUS + 14}
                textAnchor="middle"
                fontSize={SVG_TEXT_SIZE.label}
                aria-hidden
              >
                {node.caption}
                {node.stale ? ' (stale)' : ''}
              </text>
            </Link>
            {node.expandable ? (
              <g
                className="dg-expand"
                role="button"
                tabIndex={0}
                aria-label={`${node.expanded ? 'Collapse' : 'Expand'} ${node.name}`}
                aria-pressed={node.expanded}
                aria-busy={loadingIds?.has(node.id) || undefined}
                data-testid={`graph-expand-${node.id}`}
                onClick={() => onToggle?.(node)}
                onKeyDown={(event) => handleKeyDown(event, node)}
              >
                <title>{`${node.expanded ? 'Collapse' : 'Expand'} ${node.name}`}</title>
                <circle
                  className="dg-expand__hit"
                  cx={node.x + (node.column < 0 ? -NODE_RADIUS - 14 : NODE_RADIUS + 14)}
                  cy={node.y}
                  r={12}
                />
                <text
                  className="dg-expand__glyph"
                  x={node.x + (node.column < 0 ? -NODE_RADIUS - 14 : NODE_RADIUS + 14)}
                  y={node.y}
                  dy="0.35em"
                  textAnchor="middle"
                  fontSize={SVG_TEXT_SIZE.value}
                  aria-hidden
                >
                  {node.expanded ? '−' : '+'}
                </text>
              </g>
            ) : null}
          </g>
        ))}
        {layout.overflow.map((more) => (
          <text
            key={`more-${more.column}`}
            className="dg-more"
            x={more.x}
            y={more.y}
            textAnchor="middle"
            fontSize={SVG_TEXT_SIZE.label}
            data-testid={`graph-more-${more.column}`}
          >
            {`+${more.hidden} more in the list`}
          </text>
        ))}
      </svg>
    </div>
  );
}
