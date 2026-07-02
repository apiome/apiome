/**
 * Presentational copy for the branch-vs-default divergence chip (#2723 GLI-04).
 */

export type BranchDivergenceChipTone = 'muted' | 'ahead' | 'behind' | 'diverged';

export function getBranchDivergenceChipPresentation(
  ahead: number,
  behind: number,
  againstName: string
): { label: string; tone: BranchDivergenceChipTone } {
  const target = againstName.trim() || 'default branch';
  if (ahead === 0 && behind === 0) {
    return { label: `in sync with ${target}`, tone: 'muted' };
  }
  if (ahead > 0 && behind === 0) {
    return { label: `↑${ahead} ahead of ${target}`, tone: 'ahead' };
  }
  if (ahead === 0 && behind > 0) {
    return { label: `↓${behind} behind ${target}`, tone: 'behind' };
  }
  return { label: `↑${ahead} ↓${behind} diverged from ${target}`, tone: 'diverged' };
}

export function branchDivergenceChipToneClasses(tone: BranchDivergenceChipTone): string {
  const base =
    'inline-flex max-w-[min(18rem,52vw)] items-center gap-1 rounded-lg border px-2.5 py-2 text-sm font-medium shadow-md backdrop-blur-md transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30';
  switch (tone) {
    case 'muted':
      return `${base} border-gray-200/55 bg-white/45 text-gray-600 hover:border-gray-300/70 hover:bg-white/65 dark:border-gray-600/45 dark:bg-gray-900/40 dark:text-gray-400 dark:hover:border-gray-500/50 dark:hover:bg-gray-900/55`;
    case 'ahead':
      return `${base} border-emerald-300/60 bg-emerald-50/50 text-emerald-900 hover:border-emerald-400/80 hover:bg-emerald-50/70 dark:border-emerald-700/45 dark:bg-emerald-950/35 dark:text-emerald-100 dark:hover:border-emerald-600/50`;
    case 'behind':
      return `${base} border-amber-300/60 bg-amber-50/50 text-amber-950 hover:border-amber-400/80 hover:bg-amber-50/70 dark:border-amber-700/45 dark:bg-amber-950/40 dark:text-amber-100 dark:hover:border-amber-600/50`;
    case 'diverged':
    default:
      return `${base} border-indigo-300/60 bg-indigo-50/50 text-indigo-950 hover:border-indigo-400/80 hover:bg-indigo-50/70 dark:border-indigo-700/45 dark:bg-indigo-950/40 dark:text-indigo-100 dark:hover:border-indigo-600/50`;
  }
}
