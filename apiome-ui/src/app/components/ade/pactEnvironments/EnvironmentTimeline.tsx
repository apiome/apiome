'use client';

/**
 * The **History** view of the Environments page — PFX-8.13 (#7310).
 *
 * A timeline (DESIGN.md §8) of every deployment, undeployment, release and end of support in the
 * workspace, newest first: what happened, where, who recorded it, and — for a deployment or a
 * release — whether can-i-deploy said yes when it was recorded (**Not verified at the time**). A
 * replacement is told once, on the deployment that replaced the old version ("Replaced 2.6.1").
 * **Show older** reads the next page; nothing is skipped between pages.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`v-time`).
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import { formatWhen } from '@lib/pact-pacticipants';
import { eventBadge, eventDetail, eventTitle, type EventsPage, type HistoryEvent } from '@lib/pact-environment-board';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchEvents } from './environmentsApi';

/** The marker tone of an event on the timeline. */
function eventTone(event: HistoryEvent): string {
  if (event.kind === 'deployed' || event.kind === 'released') return event.verdict === 'deployable' ? 'ok' : event.verdict ? 'warn' : 'accent';
  return 'neutral';
}

/** Props for {@link EnvironmentTimeline}. */
export interface EnvironmentTimelineProps {
  /** A first page to show without reading it (fixture renders). */
  initial?: EventsPage;
}

/**
 * The history.
 *
 * @param props - See {@link EnvironmentTimelineProps}.
 * @returns The timeline.
 */
export function EnvironmentTimeline({ initial }: EnvironmentTimelineProps) {
  const [events, setEvents] = React.useState<HistoryEvent[] | null>(initial?.events ?? null);
  const [cursor, setCursor] = React.useState<string | null>(initial?.nextCursor ?? null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async (after: string | null) => {
    setBusy(true);
    setError(null);
    try {
      const page = await fetchEvents(after);
      setEvents((previous) => (after && previous ? [...previous, ...page.events] : page.events));
      setCursor(page.nextCursor);
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load the history'));
    } finally {
      setBusy(false);
    }
  }, []);

  React.useEffect(() => {
    if (!initial) void load(null);
  }, [initial, load]);

  if (error && events === null) {
    return (
      <EmptyState
        variant="compact"
        tone="danger"
        titleAs="h2"
        title="The history could not be read"
        description={error}
        action={
          <Button variant="soft" onClick={() => void load(null)}>
            <RefreshCw aria-hidden />
            Try again
          </Button>
        }
      />
    );
  }
  if (events === null) return <LoadingState message="Reading the history…" minHeightClassName="min-h-[6rem]" />;
  if (events.length === 0) {
    return (
      <EmptyState
        variant="compact"
        titleAs="h2"
        title="Nothing recorded yet"
        description="Deployments, releases and their endings appear here as they are recorded."
      />
    );
  }
  return (
    <section className="ppx__panel" aria-labelledby="penv-history-title" data-testid="penv-history">
      <h2 id="penv-history-title" className="sr-only">
        History
      </h2>
      <ol className="lw-timeline penv-timeline">
        {events.map((event) => {
          const badge = eventBadge(event);
          const detail = eventDetail(event);
          return (
            <li key={`${event.kind}:${event.uuid}`} className="lw-timeline__item" data-tone={eventTone(event)} data-testid="penv-event">
              <div className="penv-timeline__head">
                <span className="lw-timeline__title">{eventTitle(event)}</span>
                {badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : null}
              </div>
              {detail ? <div className="penv-board__sub">{detail}</div> : null}
              <div className="lw-timeline__meta">
                {formatWhen(event.at)}
                {event.actor ? ` · ${event.actor}` : ''}
              </div>
            </li>
          );
        })}
      </ol>
      {error ? (
        <p className="ppx__error" role="alert">
          {error}
        </p>
      ) : null}
      {cursor ? (
        <Button variant="outline" size="sm" onClick={() => void load(cursor)} disabled={busy} data-testid="penv-history-more">
          {busy ? 'Reading…' : 'Show older'}
        </Button>
      ) : null}
    </section>
  );
}
