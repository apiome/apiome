'use client';

/**
 * The before/after diff view (UXE-1.3).
 *
 * Red and green rows are the obvious way to draw a diff and, on their own, a
 * §27.4 violation. Three redundant cues are carried instead: a `+`/`-` marker
 * column, a per-line accessible prefix, and a countable summary sentence — so
 * the diff survives greyscale, high contrast and being read aloud.
 *
 * The line list is a `<table>` rather than styled `<div>`s because that is what
 * gives a screen-reader user row-by-row navigation with line numbers attached.
 */

import * as React from 'react';
import {
  AUTHORING_DIFF_MARKERS,
  buildAuthoringDiff,
  describeAuthoringDiffKind,
  summarizeAuthoringDiff,
} from '@lib/authoring/diff';
import { cn } from '@lib/utils';
import {
  authoringDiffLineClass,
  authoringMonoClass,
  authoringSectionTitleClass,
  authoringSurfaceClass,
} from '../../authoringClasses';

/** Props for {@link AuthoringDiffView}. */
export type AuthoringDiffViewProps = {
  /** Previous text. Empty means the content did not exist. */
  before: string;
  /** New text. Empty means the content was deleted. */
  after: string;
  /** Heading, e.g. `Description`. */
  title: string;
  /** Label for the previous side, e.g. `Production`. Defaults to `Before`. */
  beforeLabel?: string;
  /** Label for the new side, e.g. `Draft`. Defaults to `After`. */
  afterLabel?: string;
  className?: string;
};

/**
 * Render a line diff with an accessible summary.
 *
 * @param props - The two texts, a heading and optional side labels.
 */
export default function AuthoringDiffView({
  before,
  after,
  title,
  beforeLabel = 'Before',
  afterLabel = 'After',
  className,
}: AuthoringDiffViewProps) {
  const headingId = React.useId();
  // Diffing is O(n·m); recompute only when the texts actually change so
  // typing in an adjacent editor cannot re-diff on every keystroke (§27.5).
  const lines = React.useMemo(() => buildAuthoringDiff(before, after), [before, after]);
  const summary = React.useMemo(() => summarizeAuthoringDiff(lines), [lines]);

  return (
    <section
      className={cn(authoringSurfaceClass, 'flex flex-col gap-2 p-3', className)}
      aria-labelledby={headingId}
      data-testid="authoring-diff"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={headingId} className={authoringSectionTitleClass}>
          {title}
        </h3>
        <p className="text-xs text-gray-600 dark:text-gray-400" data-testid="authoring-diff-summary">
          {beforeLabel} → {afterLabel} · {summary.description}
        </p>
      </header>

      {summary.identical ? (
        <p className="px-2 py-3 text-sm text-gray-600 dark:text-gray-300">
          {beforeLabel} and {afterLabel} are identical.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <caption className="sr-only">
              {title}: {summary.description} Comparing {beforeLabel} with {afterLabel}.
            </caption>
            <thead className="sr-only">
              <tr>
                <th scope="col">Change</th>
                <th scope="col">{beforeLabel} line</th>
                <th scope="col">{afterLabel} line</th>
                <th scope="col">Content</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, index) => (
                <tr
                  key={`${line.kind}-${line.beforeLine ?? 'x'}-${line.afterLine ?? 'x'}-${index}`}
                  className={authoringDiffLineClass[line.kind]}
                  data-diff-kind={line.kind}
                >
                  {/* The marker is visible; the word is announced. */}
                  <td className={cn(authoringMonoClass, 'w-6 select-none px-1 text-center')}>
                    <span aria-hidden="true">{AUTHORING_DIFF_MARKERS[line.kind]}</span>
                    <span className="sr-only">{describeAuthoringDiffKind(line.kind)}</span>
                  </td>
                  <td className={cn(authoringMonoClass, 'w-10 select-none px-1 text-right')}>
                    {line.beforeLine ?? ''}
                  </td>
                  <td className={cn(authoringMonoClass, 'w-10 select-none px-1 text-right')}>
                    {line.afterLine ?? ''}
                  </td>
                  <td className={cn(authoringMonoClass, 'whitespace-pre-wrap px-2')}>
                    {line.text}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
