export type DirectoryStats = {
  tenant_count: number;
  project_count: number;
  version_count: number;
};

function StatPill({ value, label }: { value: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border/90 bg-surface/90 px-3 py-1 text-xs font-medium text-fg-muted shadow-xs">
      <span aria-hidden="true" className="hex inline-block h-2 w-2 bg-honey" />
      <strong className="font-semibold tabular-nums text-fg">
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
