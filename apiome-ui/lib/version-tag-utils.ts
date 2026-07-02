/** Validation for git-like version tag names (sync helpers for UI and server). */

const VERSION_TAG_NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._\-/]{0,254}$/;

export function isValidVersionTagName(name: string): boolean {
  return VERSION_TAG_NAME_RE.test(name.trim());
}
