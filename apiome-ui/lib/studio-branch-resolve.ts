import type { VersionBranchRow } from '@/app/components/ade/version-dialogs/types';

/**
 * Prefer the project default when several branches share the same tip revision.
 */
export function resolveActiveBranchForRevision(
  revisionId: string,
  branches: VersionBranchRow[]
): VersionBranchRow | null {
  const tips = branches.filter((b) => String(b.tip_version_id) === String(revisionId));
  if (tips.length === 0) return null;
  const preferred = tips.find((b) => b.is_default);
  return preferred ?? tips[0] ?? null;
}

/** Default branch first, then alphabetical by name. */
export function sortBranchesForPicker(branches: VersionBranchRow[]): VersionBranchRow[] {
  return [...branches].sort((a, b) => {
    const ad = a.is_default ? 0 : 1;
    const bd = b.is_default ? 0 : 1;
    if (ad !== bd) return ad - bd;
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  });
}
