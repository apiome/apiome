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
        <span className="mr-1 text-2xs font-medium uppercase tracking-wider text-fg-subtle">
          Refine with
        </span>
      )}
      {operators.map((op) => (
        <button
          key={op}
          type="button"
          onClick={() => onInsert(op)}
          className="rounded-md border border-border bg-surface px-2 py-0.5 font-mono text-2xs text-fg-muted shadow-xs transition-colors hover:border-accent hover:text-accent-fg"
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
    <div className="rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-4 py-2.5">
        <h3 className="text-sm! font-semibold text-fg">Search syntax</h3>
        <p className="mt-0.5 text-xs text-fg-muted">
          Combine words, phrases and filters in one box. Filters also live in the rail.
        </p>
      </div>
      <dl className="divide-y divide-border text-xs">
        {SYNTAX_HELP.map((row) => (
          <div key={row.operator} className="grid grid-cols-[6.5rem_1fr] gap-2 px-4 py-2">
            <dt>
              <code className="rounded-xs bg-subtle px-1.5 py-0.5 font-mono text-2xs text-fg">
                {row.operator}
              </code>
            </dt>
            <dd className="min-w-0 text-fg-muted">
              {row.meaning}{' '}
              {onTry ? (
                <button
                  type="button"
                  onClick={() => onTry(row.example)}
                  className="font-mono text-2xs text-accent-fg hover:underline"
                  title={`Try "${row.example}"`}
                >
                  {row.example}
                </button>
              ) : (
                <code className="font-mono text-2xs text-fg-muted">{row.example}</code>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
