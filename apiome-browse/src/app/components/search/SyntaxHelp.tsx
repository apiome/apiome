'use client';

import { SYNTAX_HELP } from '../../../../lib/search/query';

/**
 * The operator chips under a search box: one click appends `key:` to the query so a visitor
 * learns the language by using it.
 */
export function OperatorChips({
  onInsert,
  compact = false,
}: {
  onInsert: (operator: string) => void;
  compact?: boolean;
}) {
  const operators = compact
    ? ['method:', 'path:', 'org:', 'type:', 'format:']
    : ['method:', 'path:', 'org:', 'project:', 'type:', 'format:', 'paradigm:', 'tag:', 'after:', '"phrase"', '-word'];
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Search operators">
      {!compact && (
        <span className="mr-1 text-[11px] font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
          Refine with
        </span>
      )}
      {operators.map((op) => (
        <button
          key={op}
          type="button"
          onClick={() => onInsert(op)}
          className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 font-mono text-[11px] text-zinc-600 shadow-xs transition-colors hover:border-[var(--brand)] hover:text-[var(--brand)] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
        >
          {op}
        </button>
      ))}
    </div>
  );
}

/** The full syntax reference card. */
export function SyntaxHelpCard({ onTry }: { onTry?: (example: string) => void }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-800">
        <h3 className="text-[13px]! font-semibold text-zinc-900 dark:text-zinc-50">Search syntax</h3>
        <p className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400">
          Combine words, phrases and filters in one box. Filters also live in the rail.
        </p>
      </div>
      <dl className="divide-y divide-zinc-100 text-[12px] dark:divide-zinc-800/80">
        {SYNTAX_HELP.map((row) => (
          <div key={row.operator} className="grid grid-cols-[6.5rem_1fr] gap-2 px-4 py-2">
            <dt>
              <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200">
                {row.operator}
              </code>
            </dt>
            <dd className="min-w-0 text-zinc-600 dark:text-zinc-400">
              {row.meaning}{' '}
              {onTry ? (
                <button
                  type="button"
                  onClick={() => onTry(row.example)}
                  className="font-mono text-[11px] text-[var(--brand)] hover:underline"
                  title={`Try "${row.example}"`}
                >
                  {row.example}
                </button>
              ) : (
                <code className="font-mono text-[11px] text-zinc-500">{row.example}</code>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
