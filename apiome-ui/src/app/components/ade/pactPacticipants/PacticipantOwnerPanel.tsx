'use client';

/**
 * A pacticipant's **Owner** — PFX-6.4 (#6956).
 *
 * The team that owns the pacticipant (CDG-2.2 kind `pacticipant`), with **Assign owner** /
 * **Change owner** and **Confirm** on a suggestion (`EntityOwnerSection`). Its members receive
 * the Pact findings about the pacticipant — stale pacts, re-publish requests and failed
 * verifications. The section loads, fails and retries on its own, so a missing `pacts:view` on the
 * owners API never hides the rest of the page; apiome-rest checks `pacts:edit` on a change.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import { EntityOwnerSection } from '../catalogAgents/EntityOwnerSection';
import { fetchOwner } from '../owners/ownersApi';
import type { EntityOwner } from '@lib/owners';
import { describeFailure } from './describeFailure';

/** What the owner team receives, as the section says it. */
export const OWNER_DESCRIPTION =
  'Stale-pact re-publish requests and failed verifications go to this team. Without an owner they go to the owner of the consumer or project the pacticipant is bound to, else to the Unowned findings report.';

/** The owner read: loading, failed, or loaded (an owner or `null`). */
type OwnerRead = { state: 'loading' } | { state: 'failed'; error: string } | { state: 'loaded'; owner: EntityOwner | null };

/** Props for {@link PacticipantOwnerPanel}. */
export interface PacticipantOwnerPanelProps {
  /** The pacticipant's id (owners are keyed by id, not handle). */
  pacticipantId: string;
  /** Bumped by the page's **Refresh** to read the owner again. */
  refreshKey?: number;
}

/**
 * The Owner section of a pacticipant page.
 *
 * @param props - See {@link PacticipantOwnerPanelProps}.
 * @returns The section.
 */
export default function PacticipantOwnerPanel({ pacticipantId, refreshKey = 0 }: PacticipantOwnerPanelProps) {
  const [read, setRead] = React.useState<OwnerRead>({ state: 'loading' });

  const load = React.useCallback(async () => {
    setRead({ state: 'loading' });
    try {
      setRead({ state: 'loaded', owner: await fetchOwner('pacticipant', pacticipantId) });
    } catch (caught) {
      setRead({ state: 'failed', error: describeFailure(caught, 'Could not load the owner') });
    }
  }, [pacticipantId]);

  React.useEffect(() => {
    void load();
  }, [load, refreshKey]);

  if (read.state === 'loading') {
    return <LoadingState message="Reading the owner…" minHeightClassName="min-h-[4rem]" />;
  }
  if (read.state === 'failed') {
    return (
      <section className="ppx__panel" aria-label="Owner" data-testid="ppx-owner-error">
        <EmptyState
          variant="compact"
          tone="danger"
          title="The owner could not be read"
          description={read.error}
          action={
            <Button variant="soft" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Try again
            </Button>
          }
        />
      </section>
    );
  }
  return (
    <EntityOwnerSection
      kind="pacticipant"
      entityId={pacticipantId}
      owner={read.owner}
      onChanged={() => void load()}
      description={OWNER_DESCRIPTION}
    />
  );
}
