'use client';

/**
 * Analytics panel with an accessible chart summary (UXE-1.3).
 *
 * §28.4 requires every chart to offer a table view, an accessible summary and
 * an export. This primitive owns all three plus the five states a metric can be
 * in, including the one that is easy to get wrong: `threshold`, where data
 * exists but is too sparse to show without risking identification. Rendering
 * that as "no data" would be a lie, and rendering the numbers would be a leak.
 *
 * The chart itself is intentionally not drawn here. This primitive supplies the
 * frame, the states, the summary and the table; UXE-2.x plugs a chart into
 * `children` and inherits all of it for free.
 */

import * as React from 'react';
import {
  describeAuthoringAnalyticsState,
  formatAuthoringMetric,
  summarizeAuthoringSeries,
  type AuthoringAnalyticsSeries,
  type AuthoringAnalyticsState,
} from '@lib/authoring/analytics';
import { cn } from '@lib/utils';
import {
  authoringFocusClass,
  authoringMutedTextClass,
  authoringSectionTitleClass,
  authoringSurfaceClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringAnalyticsPanel}. */
export type AuthoringAnalyticsPanelProps = {
  /** Heading, e.g. `Page views`. */
  title: string;
  state: AuthoringAnalyticsState;
  /** The measured series. Required when `state` is `ready`. */
  series?: AuthoringAnalyticsSeries;
  /** The chart drawing, rendered only in the `ready` state. */
  children?: React.ReactNode;
  /** Retries a failed load. Shown only in the `error` state. */
  onRetry?: () => void;
  className?: string;
};

/**
 * Render an analytics panel in one of its five states.
 *
 * @param props - Heading, state, series and the optional chart.
 */
export default function AuthoringAnalyticsPanel({
  title,
  state,
  series,
  children,
  onRetry,
  className,
}: AuthoringAnalyticsPanelProps) {
  const headingId = React.useId();
  const [showTable, setShowTable] = React.useState(false);
  // `ready` without a series would render a chart frame around nothing, so it
  // is treated as empty rather than trusted — including in the copy, which
  // must say "no data" rather than "ready".
  const ready = state === 'ready' && series !== undefined && series.points.length > 0;
  const effectiveState = state === 'ready' && !ready ? 'empty' : state;
  const copy = describeAuthoringAnalyticsState(effectiveState);
  const summary = ready ? summarizeAuthoringSeries(series) : undefined;

  return (
    <section
      className={cn(authoringSurfaceClass, 'flex flex-col gap-3 p-4', className)}
      aria-labelledby={headingId}
      data-analytics-state={state}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={headingId} className={authoringSectionTitleClass}>
          {title}
        </h3>
        {ready ? (
          <button
            type="button"
            onClick={() => setShowTable((open) => !open)}
            aria-expanded={showTable}
            className={cn(
              'min-h-9 rounded-lg px-2 text-xs font-medium text-indigo-700 hover:underline dark:text-indigo-300',
              authoringFocusClass
            )}
          >
            {showTable ? 'Hide table' : 'View as table'}
          </button>
        ) : null}
      </header>

      {ready ? (
        <>
          {/*
           * The summary is the chart's accessible equivalent, so it is
           * associated with the drawing rather than floating beside it.
           */}
          <p className={authoringMutedTextClass} data-testid="authoring-chart-summary">
            {summary!.description}
          </p>

          {children ? (
            <div role="img" aria-label={summary!.description}>
              {children}
            </div>
          ) : null}

          {showTable ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">
                  {title} — {summary!.description}
                </caption>
                <thead>
                  <tr className="border-b border-gray-200 text-left dark:border-gray-700">
                    <th scope="col" className="px-2 py-1 font-medium">
                      Bucket
                    </th>
                    <th scope="col" className="px-2 py-1 font-medium">
                      {series!.label}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {series!.points.map((point) => (
                    <tr key={point.label} className="border-b border-gray-100 dark:border-gray-700">
                      <th scope="row" className="px-2 py-1 text-left font-normal">
                        {point.label}
                      </th>
                      <td className="px-2 py-1">
                        {formatAuthoringMetric(point.value, series!.unit)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : (
        <div
          className="flex flex-col items-start gap-2 py-4"
          role={state === 'error' ? 'alert' : 'status'}
          aria-live={state === 'error' ? 'assertive' : 'polite'}
        >
          <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-white">
            <AuthoringIcon
              name={
                state === 'loading'
                  ? 'LoaderCircle'
                  : state === 'error'
                    ? 'TriangleAlert'
                    : state === 'threshold'
                      ? 'Lock'
                      : 'BarChart3'
              }
              className="h-4 w-4 shrink-0"
            />
            {copy.title}
          </p>
          <p className={authoringMutedTextClass}>{copy.description}</p>

          {state === 'error' && onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className={cn(
                'min-h-9 rounded-lg border border-gray-300 px-3 text-sm font-medium dark:border-gray-600',
                authoringFocusClass
              )}
            >
              Retry
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}
