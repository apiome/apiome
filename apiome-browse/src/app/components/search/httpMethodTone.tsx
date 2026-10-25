'use client';

/**
 * One colour vocabulary for HTTP methods, shared by the spec viewer, the spec sidebar and the
 * search results so a `POST` reads the same everywhere.
 */
export const HTTP_METHOD_TONE: Record<string, string> = {
  get: 'bg-emerald-50 text-emerald-700 ring-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30',
  post: 'bg-sky-50 text-sky-700 ring-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/30',
  put: 'bg-amber-50 text-amber-700 ring-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30',
  patch: 'bg-blue-50 text-blue-700 ring-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/30',
  delete: 'bg-rose-50 text-rose-700 ring-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30',
  options: 'bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700',
  head: 'bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700',
  trace: 'bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700',
};

/** The tone classes for a method, falling back to the neutral tone. */
export function methodTone(method: string): string {
  return HTTP_METHOD_TONE[method.toLowerCase()] ?? HTTP_METHOD_TONE.options;
}

/** The method pill. */
export function MethodBadge({ method, size = 'md' }: { method: string; size?: 'sm' | 'md' }) {
  const dims = size === 'sm' ? 'min-w-[2.75rem] px-1.5 py-0.5 text-[10px]' : 'min-w-[3.25rem] px-2 py-0.5 text-[11px]';
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded font-mono font-semibold uppercase tracking-wide ring-1 ring-inset ${dims} ${methodTone(method)}`}
    >
      {method}
    </span>
  );
}
