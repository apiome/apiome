/** Validation for git-like version branch names (no "use server" — sync helpers for UI and server). */

const VERSION_BRANCH_NAME_RE = /^[a-zA-Z][a-zA-Z0-9._\-/]{0,254}$/;

export function isValidVersionBranchName(name: string): boolean {
  return VERSION_BRANCH_NAME_RE.test(name.trim());
}

/**
 * Suggested branch name for "branch from this revision" dialogs — user may edit (#2571).
 * Prefers `feature/<slug>` from the commit note; falls back to `branch/v<semver with dashes>`.
 */
export function suggestBranchNameFromRevision(
  shortMessage: string | null | undefined,
  semanticVersionId: string
): string {
  const raw = (shortMessage ?? '').trim().toLowerCase();
  const slug = raw
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-')
    .slice(0, 48);
  if (slug.length >= 2) {
    const candidate = `feature/${slug}`;
    if (isValidVersionBranchName(candidate)) return candidate;
  }
  const ver = (semanticVersionId ?? '').trim() || '0-0-0';
  const safe = ver.replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-+|-+$/g, '') || '0-0-0';
  return `branch/v${safe}`;
}
