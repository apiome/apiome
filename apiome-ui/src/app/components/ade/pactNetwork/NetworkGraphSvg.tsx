'use client';

/**
 * The integration network drawing — PFX-5.3 (#6947). A deterministic SVG (like the dependency
 * graph), so it renders the same in a browser, in jsdom and in the docs-screenshot fixture.
 *
 * A picture of the integrations table beside it, which stays the source of truth. Each
 * pacticipant is a link to its own network; each edge (consumer → provider) is a link to the
 * integration's newest pact. The edge is coloured by that pact's verdict and carries a mark
 * (✓ ✕ ! ?), and an unverified edge is dashed, so colour is never the only signal. A pacticipant
 * whose pacts were not or could not be read is drawn with a dashed outline.
 */

import * as React from 'react';
import Link from 'next/link';
import { SVG_TEXT_SIZE } from '@/app/components/ui/svgTypography';
import type { PactNetwork } from '@lib/pact-network';
import type { VerificationVerdict } from '@lib/pact-detail';
import {
  NODE_HEIGHT,
  NODE_WIDTH,
  VERDICT_GLYPHS,
  VERDICT_ORDER,
  networkAriaLabel,
  type NetworkLayout,
} from './networkLayoutModel';

export interface NetworkGraphSvgProps {
  network: PactNetwork;
  layout: NetworkLayout;
}

/**
 * Draw the network.
 *
 * @param props - The network and its layout.
 * @returns The drawing.
 */
export function NetworkGraphSvg({ network, layout }: NetworkGraphSvgProps) {
  const id = React.useId().replace(/:/g, '');
  return (
    <div className="pnx-plot" data-testid="pact-network-plot">
      <svg
        className="pnx-svg"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        preserveAspectRatio="xMidYMin meet"
        role="group"
        aria-label={networkAriaLabel(network, layout)}
      >
        <defs>
          {VERDICT_ORDER.map((verdict) => (
            <marker
              key={verdict}
              id={`${id}-arrow-${verdict}`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path className="pnx-arrow" data-verdict={verdict} d="M 0 0 L 10 5 L 0 10 z" />
            </marker>
          ))}
        </defs>
        {layout.edges.map((edge) => (
          <g
            key={edge.key}
            className="pnx-edge"
            data-verdict={edge.verdict}
            data-testid={`network-edge-${edge.key}`}
          >
            <Link href={edge.href} aria-label={edge.ariaLabel} className="pnx-edge__link">
              <title>{edge.ariaLabel}</title>
              <path className="pnx-edge__hit" d={edge.d} />
              <path
                className="pnx-edge__line"
                d={edge.d}
                markerEnd={`url(#${id}-arrow-${edge.verdict})`}
                data-backward={edge.backward ? '' : undefined}
              />
              <circle className="pnx-edge__mark" cx={edge.markX} cy={edge.markY} r={9} />
              <text
                className="pnx-edge__glyph"
                x={edge.markX}
                y={edge.markY}
                dy="0.35em"
                textAnchor="middle"
                fontSize={SVG_TEXT_SIZE.body}
                aria-hidden
              >
                {VERDICT_GLYPHS[edge.verdict]}
              </text>
            </Link>
          </g>
        ))}
        {layout.nodes.map((node) => (
          <g
            key={node.slug}
            className="pnx-node"
            data-centre={node.centre ? '' : undefined}
            data-gap={node.gap ?? undefined}
            data-testid={`network-node-${node.slug}`}
          >
            <Link href={node.href} aria-label={node.ariaLabel} className="pnx-node__link">
              <title>{node.ariaLabel}</title>
              <rect
                className="pnx-node__box"
                x={node.x - NODE_WIDTH / 2}
                y={node.y - NODE_HEIGHT / 2}
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx={8}
              />
              <text
                className="pnx-node__caption"
                x={node.x}
                y={node.y}
                dy="0.35em"
                textAnchor="middle"
                fontSize={SVG_TEXT_SIZE.body}
                aria-hidden
              >
                {node.caption}
                {node.gap === 'failed' || node.gap === 'not-read' ? ' …' : ''}
              </text>
            </Link>
          </g>
        ))}
        {layout.overflow.map((more) => (
          <text
            key={`more-${more.layer}`}
            className="pnx-more"
            x={more.x}
            y={more.y}
            textAnchor="middle"
            fontSize={SVG_TEXT_SIZE.label}
            data-testid={`network-more-${more.layer}`}
          >
            {`+${more.hidden} more in the table`}
          </text>
        ))}
      </svg>
    </div>
  );
}

/**
 * The key to the edge colours and marks, in words.
 *
 * @param props - How many integrations have each verdict.
 * @returns The legend.
 */
export function NetworkLegend({
  counts,
  labels,
}: {
  counts: Record<VerificationVerdict, number>;
  labels: Record<VerificationVerdict, string>;
}) {
  return (
    <ul className="pnx-legend" aria-label="Verdicts" data-testid="pact-network-legend">
      {VERDICT_ORDER.map((verdict) => (
        <li key={verdict} className="pnx-legend__item" data-verdict={verdict}>
          <span className="pnx-legend__swatch" aria-hidden>
            {VERDICT_GLYPHS[verdict]}
          </span>
          {labels[verdict]}
          <span className="ppx__meta">{counts[verdict]}</span>
        </li>
      ))}
    </ul>
  );
}
