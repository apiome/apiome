'use client';

/**
 * CatalogDriftPanel (MFI-31.3, #4400) — "What changed", at the top of the catalog item's Versions
 * tab.
 *
 * Each version a live refresh added is a drift event: the change from the version it superseded,
 * graded by the breaking-change engine. The panel lists the item's events (newest first) and shows
 * one — the event the address names (`?drift=`), else the newest undismissed one — with its counts,
 * how it was announced, and every classified change worst first. **Compare these versions** ticks
 * the two versions in the timeline below so their inline diff opens; arriving from the banner or a
 * notification link does that on its own.
 *
 * The read is lazy and one-shot, like the other panes: it runs the first time the tab is active.
 * An item without drift draws nothing, so the Versions tab is unchanged for every other item.
 */

import * as React from 'react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card } from '@/app/components/ui/Card';
import { ErrorState } from '@/app/components/ui/ErrorState';
import {
  driftBadgeLabel,
  driftCountsText,
  DRIFT_NOTIFICATION_LABEL,
  DRIFT_SEVERITY_VIEW,
  driftComparePair,
  driftPrunedNote,
  fetchDriftEvents,
  selectDriftEvent,
  type CatalogDriftEvent,
} from '../catalogDriftModel';

export interface CatalogDriftPanelProps {
  /** The catalog item. */
  itemId: string;
  /** Whether the Versions tab is active; the events are read the first time it is. */
  active: boolean;
  /** The `?drift=` event id, if the reader followed a link to one. */
  requestedEventId: string | null;
  /** Bumped when the page dismissed an event, so the panel shows it as dismissed. */
  dismissedEventId?: string | null;
  /** Tick the two versions of a drift in the timeline below. */
  onCompare: (pair: { base: string; head: string }) => void;
}

/** How the trigger reads. */
const TRIGGER_LABEL = { sweep: 'Scheduled check', manual: 'Check now' } as const;

/**
 * Render the panel. See {@link CatalogDriftPanelProps}.
 *
 * @returns The panel, or `null` while there is no drift to show.
 */
export function CatalogDriftPanel({ itemId, active, requestedEventId, dismissedEventId, onCompare }: CatalogDriftPanelProps) {
  const [events, setEvents] = React.useState<CatalogDriftEvent[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [chosenId, setChosenId] = React.useState<string | null>(requestedEventId);
  const started = React.useRef(false);
  const autoCompared = React.useRef(false);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setEvents(await fetchDriftEvents(itemId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The drift could not be loaded.');
    }
  }, [itemId]);

  React.useEffect(() => {
    if (!active || started.current) return;
    started.current = true;
    void load();
  }, [active, load]);

  React.useEffect(() => {
    if (requestedEventId) setChosenId(requestedEventId);
  }, [requestedEventId]);

  const shown = React.useMemo(() => {
    const list = (events ?? []).map((event) =>
      event.eventId === dismissedEventId && !event.dismissedAt ? { ...event, dismissedAt: new Date().toISOString() } : event,
    );
    return { list, event: selectDriftEvent(list, chosenId) };
  }, [events, chosenId, dismissedEventId]);

  // Arriving on a drift link opens its diff once, without a click.
  React.useEffect(() => {
    const event = shown.event;
    if (autoCompared.current || !event || !requestedEventId || event.eventId !== requestedEventId) return;
    const pair = driftComparePair(event);
    if (!pair) return;
    autoCompared.current = true;
    onCompare(pair);
  }, [shown.event, requestedEventId, onCompare]);

  if (error) {
    return (
      <Card className="cid-panel" data-testid="catalog-drift-panel">
        <ErrorState title="Drift could not be loaded" description={error} onRetry={() => void load()} />
      </Card>
    );
  }
  const event = shown.event;
  if (!event) return null;
  const view = DRIFT_SEVERITY_VIEW[event.severity];
  const truncated = event.changeCount > event.changes.length;
  const pair = driftComparePair(event);
  const prunedNote = driftPrunedNote(event);

  return (
    <Card className="cid-panel cid-drift-panel" data-testid="catalog-drift-panel">
      <div className="cid-drift-panel__head">
        <div>
          <h2 className="cid-drift-panel__title">What changed</h2>
          <div className="cid-drift-panel__sub">
            Each version a live refresh adds is compared with the one before it. The worst change sets the grade.
          </div>
        </div>
        {pair ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onCompare(pair)}
            data-testid="catalog-drift-compare"
          >
            Compare these versions
          </Button>
        ) : null}
      </div>

      {shown.list.length > 1 ? (
        <div className="cid-drift-panel__events" role="group" aria-label="Drift events">
          {shown.list.map((item) => (
            <button
              key={item.eventId}
              type="button"
              className="cid-drift-panel__event"
              aria-pressed={item.eventId === event.eventId}
              onClick={() => setChosenId(item.eventId)}
              data-testid={`catalog-drift-event-${item.eventId}`}
            >
              <Badge variant={DRIFT_SEVERITY_VIEW[item.severity].tone} dot>
                {DRIFT_SEVERITY_VIEW[item.severity].label}
              </Badge>
              <span className="mono">{item.versionLabel}</span>
            </button>
          ))}
        </div>
      ) : null}

      <dl className="cid-drift-panel__facts" data-testid="catalog-drift-facts">
        <div>
          <dt>Grade</dt>
          <dd>
            <Badge variant={view.tone} dot data-testid="catalog-drift-severity">
              {driftBadgeLabel(event.severity)}
            </Badge>
          </dd>
        </div>
        <div>
          <dt>Versions</dt>
          <dd className="mono">
            {event.parentVersionLabel ?? '—'}
            {event.parentVersionPruned ? ' (pruned)' : ''} → {event.versionLabel}
          </dd>
        </div>
        <div>
          <dt>Changes</dt>
          <dd>{driftCountsText(event.counts)}</dd>
        </div>
        <div>
          <dt>Found by</dt>
          <dd>{TRIGGER_LABEL[event.trigger] ?? event.trigger}</dd>
        </div>
        <div>
          <dt>Alerts</dt>
          <dd>{DRIFT_NOTIFICATION_LABEL[event.notification] ?? event.notification}</dd>
        </div>
        {event.dismissedAt ? (
          <div>
            <dt>Banner</dt>
            <dd>Dismissed</dd>
          </div>
        ) : null}
      </dl>

      {prunedNote ? (
        <div className="cid-drift-panel__pruned" data-testid="catalog-drift-pruned">
          {prunedNote}
        </div>
      ) : null}

      {event.changes.length ? (
        <table className="cid-drift-panel__changes" data-testid="catalog-drift-changes">
          <thead>
            <tr>
              <th scope="col">Grade</th>
              <th scope="col">Change</th>
              <th scope="col">Why</th>
            </tr>
          </thead>
          <tbody>
            {event.changes.map((change, index) => (
              <tr key={`${change.key ?? 'change'}-${index}`} data-severity={change.severity}>
                <td>
                  <Badge variant={DRIFT_SEVERITY_VIEW[change.severity].tone}>
                    {DRIFT_SEVERITY_VIEW[change.severity].label}
                  </Badge>
                </td>
                <td className="mono">{change.key ?? '—'}</td>
                <td>{change.rationale ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="cid-drift-panel__empty">No classified changes: the two versions differ only in ways that do not affect callers.</div>
      )}
      {truncated ? (
        <div className="cid-drift-panel__more" data-testid="catalog-drift-truncated">
          Showing the {event.changes.length} most severe of {event.changeCount} changes.
        </div>
      ) : null}
    </Card>
  );
}
