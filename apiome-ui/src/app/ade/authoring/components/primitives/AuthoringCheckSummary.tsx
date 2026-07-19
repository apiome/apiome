'use client';

/**
 * The shared checks summary (UXE-1.3).
 *
 * Release rows, publish sheets and proposal validation all report checks. They
 * render this, so the count in a list and the count in the confirmation that
 * follows it are computed by the same function and cannot disagree.
 *
 * The summary line is a `status` region: when a run finishes while the operator
 * is looking elsewhere on the page, the outcome is announced rather than only
 * appearing.
 */

import * as React from 'react';
import {
  describeAuthoringCheckStatus,
  summarizeAuthoringChecks,
  type AuthoringCheck,
} from '@lib/authoring/checks';
import { cn } from '@lib/utils';
import {
  authoringFocusClass,
  authoringSectionTitleClass,
  authoringToneHookClass,
  authoringToneSurfaceClass,
  authoringToneTextClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringCheckSummary}. */
export type AuthoringCheckSummaryProps = {
  checks: readonly AuthoringCheck[];
  /** Heading text. Defaults to `Checks`. */
  title?: string;
  /** Hide the per-check list and show only the summary strip. */
  collapsed?: boolean;
  className?: string;
};

/**
 * Render a checks summary and, unless collapsed, each individual check.
 *
 * @param props - The checks, an optional heading and the collapsed flag.
 */
export default function AuthoringCheckSummary({
  checks,
  title = 'Checks',
  collapsed = false,
  className,
}: AuthoringCheckSummaryProps) {
  const headingId = React.useId();
  const summary = summarizeAuthoringChecks(checks);

  return (
    <section className={cn('flex flex-col gap-2', className)} aria-labelledby={headingId}>
      <h3 id={headingId} className={authoringSectionTitleClass}>
        {title}
      </h3>

      <p
        role="status"
        aria-live="polite"
        data-check-tone={summary.tone}
        className={cn(
          'flex items-start gap-2 rounded-lg border p-2 text-sm',
          authoringToneSurfaceClass[summary.tone],
          authoringToneHookClass[summary.tone],
          authoringToneTextClass[summary.tone]
        )}
      >
        <AuthoringIcon
          name={summary.blocked ? 'TriangleAlert' : summary.settled ? 'Check' : 'LoaderCircle'}
          className="mt-0.5 h-4 w-4 shrink-0"
        />
        {/*
         * The short label is the visible one; the full sentence is announced.
         * Rendering both visibly would double every release row's height for
         * information a sighted reader already gets from the list below.
         */}
        <span>
          {summary.label}
          <span className="sr-only"> {summary.description}</span>
        </span>
      </p>

      {!collapsed && checks.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {checks.map((check) => {
            const status = describeAuthoringCheckStatus(check.status);

            return (
              <li
                key={check.id}
                data-check-id={check.id}
                data-check-status={check.status}
                className="flex items-start gap-2 rounded-md px-2 py-1 text-sm"
              >
                <AuthoringIcon
                  name={status.icon}
                  className={cn('mt-0.5 h-4 w-4 shrink-0', authoringToneTextClass[status.tone])}
                />
                <span className="flex min-w-0 flex-col">
                  <span className="text-gray-900 dark:text-gray-100">
                    {check.label}
                    {/* The word, not just the icon colour, states the outcome. */}
                    <span className={cn('ml-2 text-xs', authoringToneTextClass[status.tone])}>
                      {status.label}
                    </span>
                    {check.blocking ? (
                      <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                        Required
                      </span>
                    ) : null}
                  </span>
                  {check.detail ? (
                    <span className="text-xs text-gray-600 dark:text-gray-400">{check.detail}</span>
                  ) : null}
                  {check.href ? (
                    <a
                      href={check.href}
                      className={cn(
                        'text-xs text-indigo-700 hover:underline dark:text-indigo-300',
                        authoringFocusClass
                      )}
                    >
                      View evidence
                      <span className="sr-only"> for {check.label}</span>
                    </a>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
