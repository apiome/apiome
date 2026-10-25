'use client';

import { highlightSegments } from '../../../../lib/search/highlight';

/** Text with every needle wrapped in a `<mark>`. */
export function Highlight({ text, needles }: { text: string; needles: readonly string[] }) {
  const segments = highlightSegments(text, needles);
  if (segments.length === 0) return null;
  return (
    <>
      {segments.map((segment, i) =>
        segment.hit ? (
          <mark key={i} className="rounded-sm bg-[var(--gold-soft)] px-0.5 text-inherit dark:bg-amber-400/25">
            {segment.text}
          </mark>
        ) : (
          <span key={i}>{segment.text}</span>
        )
      )}
    </>
  );
}
