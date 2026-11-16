'use client';

import { forwardRef, type KeyboardEvent } from 'react';
import { sanitizeSearchInput } from '../../utils/searchValidation';
import type { FindResult } from '../../../../lib/search/findInVersion';

interface VersionFindBoxProps {
  /** The query text, as typed (`method:DELETE pets`). */
  value: string;
  /** Called with the sanitized text on every keystroke. */
  onChange: (next: string) => void;
  /** The matcher's result for `value`; null while the spec is still loading. */
  result: FindResult | null;
  /** Jump to the next (`1`, `↵`) or previous (`-1`, `⇧↵`) match. */
  onJump: (direction: 1 | -1) => void;
  /** Empty the box and show the whole version again. */
  onClear: () => void;
}

/**
 * The "find in this version" box at the top of a version page (BDX-1.3).
 *
 * It owns no state: the version page keeps the query (and mirrors it to `?find=`), runs the
 * matcher, and hands the result back here for the count and the no-match message. The input is
 * marked `data-find-primary`, which tells the global shortcut handler (`SearchPalette`) that `/`
 * should focus this box rather than open the catalog palette; ⌘K still opens the palette.
 *
 * Keys: `↵` next match, `⇧↵` previous match, `Esc` clears.
 */
export const VersionFindBox = forwardRef<HTMLInputElement, VersionFindBoxProps>(function VersionFindBox(
  { value, onChange, result, onJump, onClear },
  ref
) {
  const active = result?.active ?? false;
  const count = result?.anchors.length ?? 0;
  const noMatch = active && count === 0;

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (active && count > 0) onJump(event.shiftKey ? -1 : 1);
    } else if (event.key === 'Escape' && value) {
      event.preventDefault();
      onClear();
    }
  };

  return (
    <div className="space-y-2" data-testid="version-find">
      <div role="search" className="relative">
        <svg
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          ref={ref}
          type="search"
          name="find"
          enterKeyHint="search"
          autoComplete="off"
          spellCheck={false}
          aria-label="Find in this version"
          aria-describedby="version-find-status"
          data-find-primary="true"
          data-testid="version-find-input"
          value={value}
          onChange={(e) => onChange(sanitizeSearchInput(e.target.value))}
          onKeyDown={onKeyDown}
          placeholder="Find in this version — words, &quot;phrases&quot;, method:, path:, type:"
          className="h-10 w-full rounded-xl border border-zinc-200 bg-white pl-9 pr-32 text-[14px] text-zinc-900 placeholder-zinc-400 shadow-xs transition-colors focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder-zinc-500 [&::-webkit-search-cancel-button]:appearance-none"
        />
        <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1.5">
          {active && result && (
            <span
              data-testid="version-find-count"
              className="text-[12px] tabular-nums text-zinc-500 dark:text-zinc-400"
            >
              {count} of {result.total}
            </span>
          )}
          {active && count > 0 && (
            <button
              type="button"
              onClick={() => onJump(1)}
              aria-label="Jump to the next match"
              title="Next match (↵) · previous (⇧↵)"
              className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-[10px] font-medium text-zinc-500 transition-colors hover:text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            >
              ↵
            </button>
          )}
          {value ? (
            <button
              type="button"
              onClick={onClear}
              aria-label="Clear find"
              className="rounded-md p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          ) : (
            <kbd className="hidden rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-[10px] font-medium text-zinc-500 sm:inline-block dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
              /
            </kbd>
          )}
        </div>
      </div>
      <p id="version-find-status" role="status" aria-live="polite" className="sr-only">
        {active && result ? `${count} of ${result.total} match` : ''}
      </p>
      {noMatch && (
        <div
          data-testid="version-find-empty"
          className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-dashed border-zinc-300 bg-white/40 px-4 py-3 dark:border-zinc-700 dark:bg-zinc-900/40"
        >
          <p className="text-[13px] text-zinc-600 dark:text-zinc-400">
            Nothing in this version matches <code className="font-mono text-zinc-800 dark:text-zinc-200">{value.trim()}</code>.
          </p>
          <button
            type="button"
            onClick={onClear}
            className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Clear search
          </button>
        </div>
      )}
    </div>
  );
});
