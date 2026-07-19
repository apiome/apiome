'use client';

/**
 * Named build and deploy progress (UXE-1.3).
 *
 * §27.2 requires progress to name its phase — "Rendering 482 pages", not a bare
 * spinner — and §27.3 requires the state to remain understandable with
 * animation disabled. Both hold here because the phase list is real text: with
 * every animation off, the list still reads "Resolving sources: Complete.
 * Rendering pages: In progress. 482 of 640 pages."
 *
 * The bar is `role="progressbar"` with real values rather than a decorative
 * strip, and the announcement is throttled to phase changes — announcing every
 * percentage tick would make the region unusable.
 */

import * as React from 'react';
import {
  describeAuthoringPhaseStatus,
  summarizeAuthoringProgress,
  type AuthoringProgressPhase,
} from '@lib/authoring/progress';
import { cn } from '@lib/utils';
import {
  authoringProgressFillClass,
  authoringProgressTrackClass,
  authoringSectionTitleClass,
  authoringToneTextClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringProgressPhases}. */
export type AuthoringProgressPhasesProps = {
  phases: readonly AuthoringProgressPhase[];
  /** Heading, e.g. `Build progress`. */
  title: string;
  className?: string;
};

/**
 * Render a phased progress list with its bar and announcement.
 *
 * @param props - The phases and a heading.
 */
export default function AuthoringProgressPhases({
  phases,
  title,
  className,
}: AuthoringProgressPhasesProps) {
  const headingId = React.useId();
  const summary = summarizeAuthoringProgress(phases);

  return (
    <section className={cn('flex flex-col gap-3', className)} aria-labelledby={headingId}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={headingId} className={authoringSectionTitleClass}>
          {title}
        </h3>
        <span className={cn('text-xs font-medium', authoringToneTextClass[summary.tone])}>
          {summary.percent}%
        </span>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={summary.percent}
        aria-valuetext={summary.announcement}
        aria-labelledby={headingId}
        className={authoringProgressTrackClass}
        data-testid="authoring-progress-bar"
      >
        <div className={authoringProgressFillClass} style={{ width: `${summary.percent}%` }} />
      </div>

      {/*
       * Announced separately from the bar: `aria-valuetext` is read when the
       * bar has focus, this region reports the phase change to a user whose
       * focus is elsewhere on the page.
       */}
      <p role="status" aria-live="polite" className="sr-only">
        {summary.announcement}
      </p>

      <ol className="flex flex-col gap-1">
        {phases.map((phase) => {
          const status = describeAuthoringPhaseStatus(phase.status);

          return (
            <li
              key={phase.id}
              data-phase-id={phase.id}
              data-phase-status={phase.status}
              className="flex items-start gap-2 text-sm"
            >
              <AuthoringIcon
                name={status.icon}
                className={cn('mt-0.5 h-4 w-4 shrink-0', authoringToneTextClass[status.tone])}
              />
              <span className="flex min-w-0 flex-col">
                <span className="text-gray-900 dark:text-gray-100">
                  {phase.label}
                  {/* The status word, so the icon is never the only cue. */}
                  <span className={cn('ml-2 text-xs', authoringToneTextClass[status.tone])}>
                    {status.label}
                  </span>
                </span>
                {phase.detail ? (
                  <span className="text-xs text-gray-600 dark:text-gray-400">{phase.detail}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
