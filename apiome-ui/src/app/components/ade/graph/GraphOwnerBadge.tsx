'use client';

/**
 * An owner-team badge for a graph node (CDG-3.4, #5969): the team's name linked to its page, with
 * "suggested" spelled out when it isn't confirmed. Colour is never the only signal.
 */

import Link from 'next/link';
import type { GraphOwner } from '@lib/graph';

export interface GraphOwnerBadgeProps {
  owner: GraphOwner | null | undefined;
  testId?: string;
}

export function GraphOwnerBadge({ owner, testId = 'graph-owner' }: GraphOwnerBadgeProps) {
  if (!owner) {
    return (
      <span className="dg-owner dg-owner--none" data-testid={testId}>
        <span aria-hidden>—</span>
        <span className="sr-only">No owner</span>
      </span>
    );
  }
  return (
    <span className="dg-owner" data-status={owner.status} data-testid={testId}>
      <Link href={`/ade/dashboard/teams/${encodeURIComponent(owner.slug)}`} className="dg-owner__team">
        {owner.name}
      </Link>
      {owner.status !== 'confirmed' ? <span className="dg-owner__status">suggested</span> : null}
    </span>
  );
}
