/**
 * Render a version id with a single leading "v" prefix, avoiding a duplicate when
 * the stored value already starts with "v" (e.g. "v1" -> "v1", "1.0.0" -> "v1.0.0").
 * The UI prepends "v" for display, so a stored "v1" would otherwise show as "vv1".
 */
export function formatVersionWithPrefix(versionId: string | null | undefined): string {
  const trimmed = (versionId ?? '').trim();
  if (!trimmed) return '';
  return `v${trimmed.replace(/^v/i, '')}`;
}

/**
 * REST list/detail payloads use `shortMessage` for the revision note; legacy/UI code often used `description`.
 */
export function getVersionRevisionNote(version: {
  description?: string | null;
  shortMessage?: string | null;
}): string {
  const d = typeof version.description === 'string' ? version.description.trim() : '';
  if (d) return d;
  const s = typeof version.shortMessage === 'string' ? version.shortMessage.trim() : '';
  return s;
}

/** Label for project/version dropdowns: semver + revision note when present. */
export function formatVersionSelectorLabel(version: {
  version_id: string;
  description?: string | null;
  shortMessage?: string | null;
  published?: boolean;
}): string {
  const lock = version.published ? '🔒 ' : '';
  const note = getVersionRevisionNote(version);
  if (note) return `${lock}${version.version_id} - ${note}`;
  return `${lock}${version.version_id}`;
}
