'use client';

/**
 * Source citations for generated content (UXE-1.3).
 *
 * §28.1 requires "exact source citations" beside a proposal. The state worth
 * designing carefully is the empty one: a proposal with no citations is not a
 * tidy blank list, it is a warning that the text is ungrounded and must be
 * verified. That is rendered as a `warning` note rather than silently omitted.
 */

import * as React from 'react';
import {
  formatAuthoringCitation,
  summarizeAuthoringCitations,
  type AuthoringCitation,
} from '@lib/authoring/citations';
import { cn } from '@lib/utils';
import {
  authoringFocusClass,
  authoringMonoClass,
  authoringSectionTitleClass,
  authoringToneHookClass,
  authoringToneSurfaceClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringCitationList}. */
export type AuthoringCitationListProps = {
  citations: readonly AuthoringCitation[];
  /** Heading text. Defaults to `Sources`. */
  title?: string;
  className?: string;
};

/**
 * Render the citations backing a proposal.
 *
 * @param props - The citations to list and an optional heading.
 */
export default function AuthoringCitationList({
  citations,
  title = 'Sources',
  className,
}: AuthoringCitationListProps) {
  const headingId = React.useId();
  const summary = summarizeAuthoringCitations(citations);

  if (citations.length === 0) {
    return (
      <div
        className={cn(
          'flex items-start gap-2 rounded-lg border p-3 text-sm',
          authoringToneSurfaceClass.warning,
          authoringToneHookClass.warning,
          className
        )}
        role="note"
      >
        <AuthoringIcon name="TriangleAlert" className="mt-0.5 h-4 w-4 shrink-0" />
        <span className="text-amber-800 dark:text-amber-200">{summary}</span>
      </div>
    );
  }

  return (
    <section className={cn('flex flex-col gap-2', className)} aria-labelledby={headingId}>
      <h3 id={headingId} className={authoringSectionTitleClass}>
        {title}
        <span className="sr-only"> — {summary}</span>
      </h3>

      <ul className="flex flex-col gap-2">
        {citations.map((citation) => {
          const location = formatAuthoringCitation(citation);

          return (
            <li
              key={citation.id}
              className="rounded-lg border border-gray-200 p-2 dark:border-gray-700"
              data-citation-id={citation.id}
            >
              <div className="flex items-start gap-2">
                <AuthoringIcon
                  name="Quote"
                  className="mt-0.5 h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500"
                />
                <div className="flex min-w-0 flex-col gap-1">
                  {citation.href ? (
                    <a
                      href={citation.href}
                      className={cn(
                        'text-sm font-medium text-indigo-700 hover:underline dark:text-indigo-300',
                        authoringFocusClass
                      )}
                      // The visible label is just the target name; the
                      // accessible name carries the kind and pointer too, so
                      // the destination is unambiguous out of context.
                      aria-label={location}
                    >
                      {citation.label}
                    </a>
                  ) : (
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {citation.label}
                    </span>
                  )}

                  <span className={authoringMonoClass}>
                    {citation.sourcePointer ?? citation.stableKey}
                  </span>

                  {citation.excerpt ? (
                    <blockquote className="border-l-2 border-gray-200 pl-2 text-xs italic text-gray-600 dark:border-gray-600 dark:text-gray-400">
                      {citation.excerpt}
                    </blockquote>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
