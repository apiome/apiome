export type DirectoryStats = {
  tenant_count: number;
  project_count: number;
  version_count: number;
};

function StatPill({ value, label }: { value: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200/90 bg-white/90 px-3 py-1 text-[12px] font-medium text-zinc-600 shadow-xs dark:border-zinc-700/90 dark:bg-zinc-950/90 dark:text-zinc-400">
      <span aria-hidden="true" className="hex inline-block h-2 w-2 bg-[var(--gold)]" />
      <strong className="font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
        {value.toLocaleString()}
      </strong>
      {label}
    </span>
  );
}

export function DirectoryStatPills({
  stats,
  className = '',
}: {
  stats: DirectoryStats;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-wrap items-center justify-center gap-2 ${className}`.trim()}
      aria-label="Directory totals"
    >
      <StatPill value={stats.tenant_count} label="Organizations" />
      <StatPill value={stats.project_count} label="Projects" />
      <StatPill value={stats.version_count} label="Published versions" />
    </div>
  );
}
