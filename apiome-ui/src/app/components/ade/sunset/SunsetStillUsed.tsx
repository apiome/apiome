'use client';

/**
 * "Still used by N consumers" — sunset readiness on a revision (RDG-5.3, #5788).
 *
 * The sunset timeline's Notes cell and the Published page's version cell both draw this line
 * for a deprecated revision, from the `stillUsed` block of `GET /v1/versions/{tenant}/
 * sunset-timeline`. Three readings:
 *
 * - **bound** — `Still used by 2 consumers (1,240 calls, 7-day)`, the first handles, and a
 *   **Consumers** link to the project's Consumers page;
 * - **anonymous** — `Anonymous traffic only — bind consumers to attribute it`, linking to the
 *   same page as **Bind consumers**;
 * - **unused** — `No traffic in the last 7 days`, quiet and with no link.
 *
 * A row with no usage evidence (no usage source on its project) draws nothing at all.
 *
 * @see `./sunsetModel.ts` — {@link sunsetUsageView}, the rules this draws.
 */

import * as React from 'react';
import Link from 'next/link';
import { Activity, ArrowRight } from 'lucide-react';

import { sunsetUsageView, type SunsetUsage } from './sunsetModel';

/** Props for {@link SunsetStillUsed}. */
export interface SunsetStillUsedProps {
  /** The row's `stillUsed` block; nothing is drawn for `null` or `undefined`. */
  usage: SunsetUsage | null | undefined;
  /** The `data-testid` of the line's wrapper. */
  testId?: string;
}

/**
 * Render the usage line, or nothing.
 *
 * @param props See {@link SunsetStillUsedProps}.
 * @returns The line, its handles and its link — or `null`.
 */
export function SunsetStillUsed({ usage, testId }: SunsetStillUsedProps) {
  const view = sunsetUsageView(usage);
  if (!view) return null;
  return (
    <div className="stl-usage" data-state={view.state} data-testid={testId}>
      <span className="stl-usage__line">
        <Activity aria-hidden />
        {view.summary}
      </span>
      {view.handles.length > 0 ? (
        <span className="stl-usage__handles mono">
          {view.handles.join(', ')}
          {view.moreHandles > 0 ? ` +${view.moreHandles} more` : ''}
        </span>
      ) : null}
      {view.href ? (
        <Link href={view.href} className="stl-usage__link">
          {view.linkLabel}
          <ArrowRight aria-hidden />
        </Link>
      ) : null}
    </div>
  );
}

export default SunsetStillUsed;
