/** Align with apiome-rest `version_notes.DEFAULT_VERSION_NOTES_LIMITS` until tenant policy is loaded from the API. */
export const VERSION_NOTES_LIMITS = {
  maxShortMessageChars: 2000,
  maxChangelogChars: 65535,
  requireShortMessage: true,
} as const;

/** REST `_AUTHOR_OR_REF_MAX_CHARS` for optional `externalRef` on commit (#2564). */
export const COMMIT_EXTERNAL_REF_MAX_CHARS = 500;

export function validateVersionNotesClient(
  shortMessage: string,
  changelog: string
): { ok: true } | { ok: false; error: string } {
  const sm = shortMessage.trim();
  const cl = changelog.trim();
  if (VERSION_NOTES_LIMITS.requireShortMessage && !sm) {
    return { ok: false, error: 'Revision note is required' };
  }
  if (sm.length > VERSION_NOTES_LIMITS.maxShortMessageChars) {
    return {
      ok: false,
      error: `Revision note exceeds ${VERSION_NOTES_LIMITS.maxShortMessageChars} characters`,
    };
  }
  if (cl.length > VERSION_NOTES_LIMITS.maxChangelogChars) {
    return {
      ok: false,
      error: `Changelog exceeds ${VERSION_NOTES_LIMITS.maxChangelogChars} characters`,
    };
  }
  return { ok: true };
}

/** Best-effort lines for downstream breaking-changes / migration docs (#746, #747). */
export function extractBreakingHintsFromChangelog(changelog: string | null | undefined): string[] {
  if (!changelog) return [];
  const out: string[] = [];
  for (const raw of changelog.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const lower = line.replace(/^[-*•]\s*/, '').trim().toLowerCase();
    if (lower.startsWith('breaking:') || lower.startsWith('breaking ')) {
      out.push(line);
    }
  }
  return out;
}
