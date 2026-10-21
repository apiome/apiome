'use client';

/**
 * Home's "Time spent" panel (#544).
 *
 * The reader's own active time per project in the current workspace, over the last 7 or 30 days:
 * a bar per project (at most five, longest first) and the total across every project. Time is
 * counted on a project's Versions page while the tab is visible and in use — `useProjectTimeTracker`
 * — and nobody but the reader ever sees theirs.
 *
 * Both windows arrive in one payload, so switching is instant and costs no request. Each bar's
 * figure is in its label as well as in its length, and the total is a sentence, so nothing is
 * carried by the bars alone.
 */

import * as React from 'react';
import Link from 'next/link';

import { Card } from '@/app/components/ui/Card';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { Skeleton } from '@/app/components/ui/Skeleton';
import {
  TIME_SPENT_WINDOWS,
  formatDuration,
  timeSpentBars,
  type TimeSpent as TimeSpentData,
  type TimeSpentWindow,
} from '@lib/db/dashboard-home-model';
import { continueCardHref } from './ContinueWorking';
import { PANEL } from './homeModel';

/** Props for {@link TimeSpent}. */
export interface TimeSpentProps {
  /** Both windows' figures. */
  timeSpent: TimeSpentData;
  /** True until the first load resolves. */
  loading: boolean;
  /** The window to open on. Defaults to the last 7 days. */
  defaultWindow?: TimeSpentWindow;
}

/**
 * The panel's closing sentence.
 *
 * @param total Active seconds across every project in the window.
 * @param span 7 or 30.
 * @returns E.g. `"4h 20m on projects in the last 7 days"`.
 */
export function timeSpentSummary(total: number, span: TimeSpentWindow): string {
  return `${formatDuration(total)} on projects in the last ${span} days`;
}

/**
 * Draw the panel.
 *
 * @param props See {@link TimeSpentProps}.
 * @returns The card, its skeleton, or its empty state.
 */
export function TimeSpent({ timeSpent, loading, defaultWindow = 7 }: TimeSpentProps) {
  const [span, setSpan] = React.useState<TimeSpentWindow>(defaultWindow);
  const titleId = React.useId();

  if (loading) {
    return (
      <Card className="home-time" aria-hidden>
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </Card>
    );
  }

  const bars = timeSpentBars(timeSpent, span);
  const total = span === 7 ? timeSpent.total7 : timeSpent.total30;

  return (
    <Card className="home-time" role="group" aria-labelledby={titleId} data-testid="home-time-spent">
      <div className="home-time__head">
        <h2 id={titleId}>{PANEL.timeSpent.title}</h2>
        <Segmented
          size="sm"
          value={String(span)}
          onValueChange={(next) => setSpan(Number(next) as TimeSpentWindow)}
          aria-label="Time window"
        >
          {TIME_SPENT_WINDOWS.map((days) => (
            <SegmentedItem key={days} value={String(days)} data-testid={`home-time-${days}`}>
              {days} days
            </SegmentedItem>
          ))}
        </Segmented>
      </div>

      {bars.length > 0 ? (
        <>
          <ol className="home-time__rows">
            {bars.map((bar) => (
              <li key={bar.projectId}>
                <Link
                  href={continueCardHref(bar.projectId)}
                  className="home-time__row"
                  data-time-project={bar.projectId}
                >
                  <span className="home-time__label">
                    <span className="home-time__name">{bar.projectName}</span>
                    <span className="home-time__value">{formatDuration(bar.seconds)}</span>
                  </span>
                  <span className="home-time__track" aria-hidden>
                    <span className="home-time__bar" style={{ width: `${bar.percent}%` }} />
                  </span>
                </Link>
              </li>
            ))}
          </ol>
          <p className="home-time__total">{timeSpentSummary(total, span)}</p>
        </>
      ) : (
        <EmptyState
          brand
          variant="compact"
          title={`No time in the last ${span} days`}
          description="Time counts while a project's versions are open and you are using the page."
        />
      )}
    </Card>
  );
}

export default TimeSpent;
